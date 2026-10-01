"""Read approved Oculus files, project known fields, and never execute code."""
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .models import (
    InspectionContext, InspectionsPage, InspectionSummary, PatchLocation,
    Project, ProjectsPage, SavedItem, SavedItemsPage,
)

MAX_FILE_BYTES = 4 * 1024 * 1024
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class DataError(ValueError):
    """An actionable, sanitized adapter error."""


def text(value, limit=1024):
    return value[:limit] if isinstance(value, str) else None


def provider(value):
    if value is None:
        return "github"
    if value not in ("github", "codeberg"):
        raise DataError("Unsupported forge provider in Oculus data.")
    return value


def repository(value):
    if not isinstance(value, str) or len(value) > 512 or not REPOSITORY.fullmatch(value):
        raise DataError("Invalid repository identity in Oculus data.")
    if any(part in (".", "..") for part in value.split("/")):
        raise DataError("Invalid repository identity in Oculus data.")
    return value


def relative_path(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise DataError("Invalid repository-relative path.")
    if value.startswith("/") or "\\" in value or any(p in (".", "..", "") for p in value.split("/")):
        raise DataError("Invalid repository-relative path.")
    return str(PurePosixPath(value))


def source_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc in ("github.com", "codeberg.org"):
            return value
    except ValueError:
        pass
    return None


def page(items, offset, limit):
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise DataError("offset must be a nonnegative integer.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise DataError("limit must be between 1 and 50.")
    end = offset + limit
    return items[offset:end], len(items), end if end < len(items) else None


class FileBackend:
    def __init__(self, state_file: Path, tracking_file: Path | None = None):
        self.state_file = state_file.expanduser()
        self.tracking_file = tracking_file.expanduser() if tracking_file else None

    @staticmethod
    def _read(path, label):
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise DataError(f"{label} exceeds the 4 MiB input limit.")
            data = json.loads(raw)
        except FileNotFoundError:
            raise DataError(f"{label} is missing; configure its startup path.") from None
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            raise DataError(f"{label} cannot be read as a JSON object.") from None
        if not isinstance(data, dict):
            raise DataError(f"{label} must be a JSON object.")
        return data

    def list_tracked_projects(self, offset=0, limit=20):
        tracking = self.tracking_file is not None
        data = self._read(self.tracking_file if tracking else self.state_file,
                          "Tracking file" if tracking else "State file")
        if tracking and (type(data.get("version")) is not int or data["version"] != 1):
            raise DataError("Tracking file must use version 1.")
        projects = []

        def visit(entries, groups=()):
            if len(groups) > 64 or not isinstance(entries, list):
                raise DataError("Tracking entries must be arrays nested at most 64 levels.")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise DataError("Each tracked project must be an object.")
                if "children" in entry:
                    name = text(entry.get("name"))
                    if not name or "repository" in entry or "provider" in entry:
                        raise DataError("Invalid tracking group.")
                    visit(entry["children"], (*groups, name))
                else:
                    repo = repository(entry.get("repository"))
                    forge = provider(entry.get("provider"))
                    if tracking and "provider" not in entry:
                        raise DataError("Tracking file projects require a provider.")
                    projects.append(Project(
                        provider=forge, repository=repo, name=text(entry.get("name")),
                        path=relative_path(entry.get("path")), groups=list(groups),
                        url=f"https://{'github.com' if forge == 'github' else 'codeberg.org'}/{repo}",
                    ))

        visit(data.get("projects", []))
        rows, total, next_offset = page(projects, offset, limit)
        return ProjectsPage(projects=rows, total=total, next_offset=next_offset,
                            source="tracking_file" if tracking else "state_file")

    def list_saved_items(self, offset=0, limit=20):
        entries = self._read(self.state_file, "State file").get("saved_items", [])
        if not isinstance(entries, list):
            raise DataError("saved_items must be an array.")
        items = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not isinstance(entry.get("event"), dict):
                raise DataError("Invalid saved item; expected key and event.")
            event = entry["event"]
            source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
            repo_data = event.get("repo") if isinstance(event.get("repo"), dict) else {}
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            record = payload.get("pull_request") or payload.get("issue") or {}
            record = record if isinstance(record, dict) else {}
            repo = source.get("repository") or repo_data.get("name")
            items.append(SavedItem(
                key=text(entry["key"]), provider=provider(source.get("provider") or event.get("provider")),
                repository=repository(repo) if repo else None,
                event_type=text(event.get("type")), title=text(record.get("title") or event.get("title")),
                url=source_url(record.get("html_url") or event.get("html_url") or event.get("url")),
                created_at=text(event.get("created_at")),
            ))
        rows, total, next_offset = page(items, offset, limit)
        return SavedItemsPage(items=rows, total=total, next_offset=next_offset)

    def _inspections(self):
        cache = self._read(self.state_file, "State file").get("inspect_overviews", {})
        # Lua can encode an empty table as [] instead of {}.
        if cache == []:
            return {}
        if not isinstance(cache, dict) or any(not isinstance(value, dict) for value in cache.values()):
            raise DataError("inspect_overviews must be an object of cached overviews.")
        return cache

    def list_inspections(self, offset=0, limit=20):
        items = []
        for key, cached in self._inspections().items():
            if len(key) > 1024:
                raise DataError("Inspection identifier exceeds the length limit.")
            locations = cached.get("locations", [])
            if not isinstance(locations, list):
                raise DataError("Cached inspection locations must be an array.")
            items.append(InspectionSummary(inspection_id=key,
                has_explanation=bool(text(cached.get("explanation"))), location_count=len(locations)))
        rows, total, next_offset = page(items, offset, limit)
        return InspectionsPage(inspections=rows, total=total, next_offset=next_offset)

    def get_inspection_context(self, inspection_id):
        # An exact dictionary lookup, never a filename, command, or Lua expression.
        if not isinstance(inspection_id, str) or not 1 <= len(inspection_id) <= 1024:
            raise DataError("Invalid inspection identifier.")
        cached = self._inspections().get(inspection_id)
        if cached is None:
            raise DataError("Inspection not found; use list_inspections to discover cached IDs.")
        locations = cached.get("locations", [])
        if not isinstance(locations, list):
            raise DataError("Cached inspection locations must be an array.")
        projected = []
        for location in locations[:3]:
            if not isinstance(location, dict):
                raise DataError("Invalid cached patch location.")
            line = location.get("line")
            projected.append(PatchLocation(path=relative_path(location.get("path")) or "",
                line=line if type(line) is int and line > 0 else None,
                reason=text(location.get("reason"))))
        return InspectionContext(inspection_id=inspection_id,
            explanation=text(cached.get("explanation"), 8000),
            explanation_model=text(cached.get("explanation_model")),
            locations=projected, patch_model=text(cached.get("patch_model")))
