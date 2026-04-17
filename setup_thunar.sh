#!/bin/bash
# Script to add CloudBridge actions to Thunar Custom Actions (UCA)

UCA_FILE="$HOME/.config/Thunar/uca.xml"
PROJECT_ROOT="$(pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python3"

if [ ! -f "$UCA_FILE" ]; then
    echo "Thunar UCA file not found. Creating a new one..."
    mkdir -p "$(dirname "$UCA_FILE")"
    echo '<?xml version="1.0" encoding="UTF-8"?>
<actions>
</actions>' > "$UCA_FILE"
fi

# Function to add an action if it doesn't exist
add_action() {
    local name="$1"
    local description="$2"
    local command="$3"
    local pattern="$4"
    
    if grep -q "$name" "$UCA_FILE"; then
        echo "Action '$name' already exists, skipping..."
        return
    fi

    # Prepare the XML snippet
    local xml="<action>
	<icon>system-run</icon>
	<name>$name</name>
	<unique-id>$(date +%s%N)</unique-id>
	<command>$command</command>
	<description>$description</description>
	<patterns>$pattern</patterns>
	<other-files/>
	<text-files/>
	<image-files/>
	<audio-files/>
	<video-files/>
</action>"

    # Escape newlines for sed
    local escaped_xml=$(echo "$xml" | sed ':a;N;$!ba;s/\n/\\n/g')

    # Insert before the closing </actions> tag
    sed -i "s|<\/actions>|$escaped_xml\\n<\/actions>|" "$UCA_FILE"
    echo "Added action: $name"
}

add_action "CloudBridge: Make Online-Only" "Upload to cloud and leave 0-byte placeholder" "$VENV_PYTHON -m cloudbridge make-online-only %f" "*"
add_action "CloudBridge: Bring Offline" "Download full content from cloud" "$VENV_PYTHON -m cloudbridge bring-offline %f" "*"
add_action "CloudBridge: Share Link" "Get public cloud link" "$VENV_PYTHON -m cloudbridge share %f" "*"
add_action "CloudBridge: Sync Now" "Run synchronization" "$VENV_PYTHON -m cloudbridge sync" "*"

echo "Thunar actions added! Please restart Thunar (thunar -q) to see changes."
