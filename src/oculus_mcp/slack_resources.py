"""Read-only Slack provisioning references for Oculus organization plans."""
import json


def workspace_creation_resource() -> str:
    return json.dumps({
        "oculusEntity": "organization",
        "slackEntity": "workspace (team)",
        "method": "admin.teams.create",
        "endpoint": "https://slack.com/api/admin.teams.create",
        "requirements": [
            "Slack Enterprise plan",
            "Org admin user token with admin.teams:write",
        ],
        "bodyExample": {
            "team_domain": "oculus-builders",
            "team_name": "Oculus Builders",
            "team_description": "Build Oculus together",
            "team_discoverability": "invite_only",
        },
        "fieldRules": {
            "team_domain": "Required, at most 21 characters; must be available in Slack.",
            "team_name": "Required display name.",
            "team_description": "Optional description.",
            "team_discoverability": "Optional: open, closed, invite_only, or unlisted.",
        },
        "afterSuccess": "Record the returned team ID (T...) on the Oculus organization.",
        "existingWorkspace": "Associate an existing Slack workspace ID instead of calling this Enterprise-only method.",
        "oculusPlanEndpoint": "GET /api/organizations/{organizationId}/slack-plan (authenticated Oculus Web API)",
    }, indent=2)


def group_creation_resource() -> str:
    return json.dumps({
        "oculusEntity": "organization group",
        "slackEntities": ["private channel", "@mention user group"],
        "steps": [
            {
                "method": "conversations.create",
                "endpoint": "https://slack.com/api/conversations.create",
                "scope": "groups:write",
                "bodyExample": {"name": "design-circle", "is_private": True},
                "afterSuccess": "Record the returned channel ID (C... or G...) on the Oculus group.",
            },
            {
                "method": "usergroups.create",
                "endpoint": "https://slack.com/api/usergroups.create",
                "scope": "usergroups:write",
                "bodyExample": {
                    "name": "Design Circle",
                    "handle": "design-circle-members",
                    "description": "Design discussions",
                    "channels": "C12345678",
                },
                "afterSuccess": "Record the returned user group ID (S...) on the Oculus group.",
            },
            {
                "method": "usergroups.users.update",
                "endpoint": "https://slack.com/api/usergroups.users.update",
                "scope": "usergroups:write",
                "bodyExample": {"usergroup": "S12345678", "users": ["U12345678", "U87654321"]},
                "condition": "Use only after every intended member has a verified Slack user ID. This call replaces the whole membership list.",
            },
        ],
        "fieldRules": {
            "name": "Channel name: lowercase letters, digits, hyphens, or underscores; at most 80 characters.",
            "team_id": "Include the target workspace ID when using a Slack org-level token.",
            "channels": "Comma-separated Slack channel IDs, available after channel creation.",
            "handle": "Choose a mention handle distinct from the channel name; Slack requires global uniqueness across channels, users, and user groups.",
            "users": "Slack user IDs, never Oculus account IDs or email addresses.",
        },
        "requirements": [
            "User groups require a Slack plan and workspace permissions that support them.",
            "Slack tokens are not included in Oculus resources or plans.",
        ],
        "oculusPlanEndpoint": "GET /api/organizations/{organizationId}/slack-plan (authenticated Oculus Web API)",
    }, indent=2)
