#!/usr/bin/env python3
"""Create a public Phase 2B Make blueprint from a private export.

The script changes account-specific connection, spreadsheet, Drive, and
Slack values only. Scenario structure, filters, mappings, error handlers,
OpenAI settings, and module IDs are preserved.
"""

import argparse
import json
import re
from pathlib import Path


CONNECTIONS = {
    "google-sheets": (100000001, "Google Sheets Connection (reconnect required)"),
    "openai-gpt-3": (100000002, "OpenAI Connection (reconnect required)"),
    "slack": (100000003, "Slack Connection (reconnect required)"),
    "google-email": (100000004, "Gmail Connection (reconnect required)"),
}

SPREADSHEET_ID = "YOUR_SPREADSHEET_ID"
SPREADSHEET_PATH = "/YOUR_GOOGLE_DRIVE_FOLDER_ID/YOUR_SPREADSHEET_ID"
DRIVE_BREADCRUMB = ["YOUR_GOOGLE_DRIVE_FOLDER", "YOUR_SPREADSHEET"]
SLACK_CHANNEL_ID = "YOUR_SLACK_CHANNEL_ID"
SLACK_CHANNEL_LABEL = "YOUR_SLACK_CHANNEL"
PUBLIC_SCENARIO_NAME = "Gmail Support Assistant - Phase 2B Candidate"

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+")


def connection_for(module_name):
    for prefix, value in CONNECTIONS.items():
        if module_name.startswith(prefix + ":"):
            return value
    return None


def sanitize_module(module):
    connection = connection_for(module.get("module", ""))
    if connection is not None:
        connection_id, connection_label = connection
        parameters = module.get("parameters")
        if isinstance(parameters, dict) and "__IMTCONN__" in parameters:
            parameters["__IMTCONN__"] = connection_id
        restore_parameters = (
            module.get("metadata", {})
            .get("restore", {})
            .get("parameters", {})
        )
        restored_connection = restore_parameters.get("__IMTCONN__")
        if isinstance(restored_connection, dict):
            restored_connection["label"] = connection_label

    if module.get("module", "").startswith("slack:"):
        mapper = module.get("mapper")
        if isinstance(mapper, dict) and "channel" in mapper:
            mapper["channel"] = SLACK_CHANNEL_ID
        restored_channel = (
            module.get("metadata", {})
            .get("restore", {})
            .get("expect", {})
            .get("channel")
        )
        if isinstance(restored_channel, dict):
            restored_channel["label"] = SLACK_CHANNEL_LABEL


def sanitize_tree(value, ancestors=()):
    if isinstance(value, dict):
        if "module" in value and "id" in value:
            sanitize_module(value)
        for key, child in list(value.items()):
            if key == "spreadsheetId" and isinstance(child, str):
                value[key] = SPREADSHEET_PATH if child.startswith("/") else SPREADSHEET_ID
            elif key == "path" and "spreadsheetId" in ancestors and isinstance(child, list):
                value[key] = list(DRIVE_BREADCRUMB)
            else:
                sanitize_tree(child, ancestors + (key,))
    elif isinstance(value, list):
        for child in value:
            sanitize_tree(child, ancestors)


def validate_public_output(value):
    raw = json.dumps(value, ensure_ascii=False)
    non_example_emails = [
        email for email in EMAIL_RE.findall(raw)
        if email.split("@")[-1].lower() != "example.com"
    ]
    if non_example_emails:
        raise ValueError("non-public email remains in sanitized output")
    if ".slack.com" in raw.lower():
        raise ValueError("Slack workspace hostname remains in sanitized output")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="private Make blueprint export")
    parser.add_argument("output", type=Path, help="public sanitized output path")
    args = parser.parse_args()

    blueprint = json.loads(args.input.read_text(encoding="utf-8"))
    blueprint["name"] = PUBLIC_SCENARIO_NAME
    sanitize_tree(blueprint)
    validate_public_output(blueprint)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(blueprint, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
