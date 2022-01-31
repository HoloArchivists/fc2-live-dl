#!/bin/bash

# Exit on error
set -e

# Get versions
py_version=$(grep 'version' setup.cfg | sed 's/version = //')
latest_tag=$(git tag --sort=-v:refname | head -n 1 | sed 's/v//')

# Skip if latest tag is the same as current version
if [ "$py_version" == "$latest_tag" ]; then
    echo "Latest version is already tagged."
    exit 0
fi

# Make sure we're in the right branch
if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
    echo "You must be in the main branch to run this script"
    exit 1
fi

# Make sure working tree is clean
if [ -n "$(git status --porcelain)" ]; then
    echo "Working tree is not clean. Please commit or stash changes before running this script."
    exit 1
fi

# Create a new tag
git tag -a "v$py_version" -em "$(git-cliff -ut $py_version -s all)"
