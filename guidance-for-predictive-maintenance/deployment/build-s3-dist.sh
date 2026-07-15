#!/bin/bash

set -e && [[ "$DEBUG" == 'true' ]] && set -x

# Get reference for all important folders
ROOT_DIR="$(dirname "$(dirname "$(realpath "$0")")")"
SOURCE_DIR="$ROOT_DIR/source"
INFRASTRUCTURE_DIR="$SOURCE_DIR/infrastructure"
DEPLOYMENT_DIR="$ROOT_DIR/deployment"
STAGING_DIST_DIR="$DEPLOYMENT_DIR/staging"
GLOBAL_ASSETS_DIR="$DEPLOYMENT_DIR/global-s3-assets"
REGIONAL_ASSETS_DIR="$DEPLOYMENT_DIR/regional-s3-assets"
LAMBDA_ZIP_OUTPUT_PATH="$DEPLOYMENT_DIR/dist/lambda"

printf "%b[Init] Remove old dist files from previous runs\n%b" "${GREEN}" "${NC}"
rm -rf "$GLOBAL_ASSETS_DIR"
rm -rf "$REGIONAL_ASSETS_DIR"
rm -rf "$STAGING_DIST_DIR"
rm -rf "$LAMBDA_ZIP_OUTPUT_PATH"

mkdir -p "$GLOBAL_ASSETS_DIR"
mkdir -p "$REGIONAL_ASSETS_DIR"
mkdir -p "$STAGING_DIST_DIR"
mkdir -p "$LAMBDA_ZIP_OUTPUT_PATH"

cd "$ROOT_DIR"

lambda_handlers_base_dir="${LAMBDA_HANDLERS_BASE_DIR:-$ROOT_DIR/source/lambda}"
lambda_zip_output_path="${LAMBDA_ZIP_OUTPUT_PATH:-$ROOT_DIR/dist/lambda}"


printf "%b[Build] Build project specific assets\n%b" "${GREEN}" "${NC}"
while IFS= read -r lambda_dir; do
  lambda_dir_name="$(basename "$lambda_dir")"

  printf "%s\n" "Building lambda dist: ${lambda_dir}"
  # Zip lambda source code into folder
  cd "$lambda_dir"
  zip -r "$lambda_zip_output_path/$lambda_dir_name.zip" . -x "*node_modules*" >/dev/null
done < <(find "$lambda_handlers_base_dir" -not -path "*__pycache__*" -mindepth 1 -maxdepth 1 -type d)

printf "%b[Synth] Synthesize Stack\n%b" "${GREEN}" "${NC}"
cd "$ROOT_DIR"

# Run cdk synth to generate CloudFormation template
poetry -C "$INFRASTRUCTURE_DIR" run cdk synth --output="$STAGING_DIST_DIR" >>/dev/null

printf "%b[Packing] Template artifacts\n%b" "${GREEN}" "${NC}"
rm -f "$STAGING_DIST_DIR/tree.json"
rm -f "$STAGING_DIST_DIR/manifest.json"
rm -f "$STAGING_DIST_DIR/cdk.out"

for f in "$STAGING_DIST_DIR"/*.template.json; do
  mv "$f" "${f%.template.json}.template";
  mv "${f%.template.json}.template" "$GLOBAL_ASSETS_DIR";
done

cd "$DEPLOYMENT_DIR/cdk-solution-helper"
node index
cd "$ROOT_DIR"

printf "%b[Packing] Updating placeholders\n%b" "${GREEN}" "${NC}"
sedi=(-i)
if [[ "$OSTYPE" == "darwin"* ]]; then
  sedi=(-i "")
fi

for file in "$GLOBAL_ASSETS_DIR"/*.template; do
  sed "${sedi[@]}" -E "s/\"\/([^asset][a-z0-9]+.zip)\"/\"\/asset\1\"/g" "$file"
done

printf "%b[Packing] Source code artifacts\n%b" "${GREEN}" "${NC}"
# For each asset.*.zip source code artifact in the temporary /staging folder
while IFS= read -r f; do
  # Rename the artifact, removing the period for handler compatibility
  zip_file_name="$(basename "$f")"
  modified_zip_file_name="${zip_file_name/asset\./asset}"

  # Copy the artifact from /staging to /regional-s3-assets
  mv "$f" "$REGIONAL_ASSETS_DIR/$modified_zip_file_name"
done < <(find "$STAGING_DIST_DIR" -name "*.zip" -mindepth 1 -maxdepth 1 -type f)

while IFS= read -r d; do
  # Rename the artifact, removing the period for handler compatibility
  dir_name="$(basename "$d")"
  modified_dir_name="${dir_name/\./}"

  # Zip artifacts from asset folder
  cd "$d"
  zip -r "$STAGING_DIST_DIR/$modified_dir_name.zip" . >/dev/null
  cd "$ROOT_DIR"

  # Copy the zipped artifact from /staging to /regional-s3-assets
  mv "$STAGING_DIST_DIR/$modified_dir_name.zip" "$REGIONAL_ASSETS_DIR"

  # Remove the old artifacts from /staging
  rm -rf "$d"
done < <(find "$STAGING_DIST_DIR" -mindepth 1 -maxdepth 1 -type d)

printf "%bBuild script finished.\n%b" "${GREEN}" "${NC}"
