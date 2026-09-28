#!/usr/bin/env bash
# publish-config.sh — static config for publish-to-github.sh
# Sourced by publish-to-github.sh; do not execute directly.

# Sanity check: must be run from inside a git repo
_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || { echo "ERROR: publish-config.sh must be sourced from within a git repo" >&2; return 1; }

export GITHUB_REMOTE_URL="git@github.com:aws-solutions-library-samples/guidance-for-automotive-data-platform-on-aws.git"
export PUBLISH_BRANCH="main"
export PUBLISH_EXCLUDE_FILE="${_REPO_ROOT}/.publish-exclude"
export SECRETS_SCAN_CONFIG="${_REPO_ROOT}/.publish-secrets-scan.yml"
# R4 fix: canonical publish-to-github.sh reads MKTEMP_PREFIX for the staging dir name.
# ADP was seeded from CMS and previously used the CMS-labelled prefix cms-publish-.
# Set the correct ADP prefix here so staging dirs are named adp-publish-<tag>-*.
export MKTEMP_PREFIX="adp-publish-"
