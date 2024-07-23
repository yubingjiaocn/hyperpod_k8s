#!/bin/bash

set -ex

LOG_FILE="/var/log/provision/provisioning.log"
mkdir -p "/var/log/provision"
touch $LOG_FILE

# Function to log messages
logger() {
  echo "$@" | tee -a $LOG_FILE
}

if [[ -z "$SAGEMAKER_RESOURCE_CONFIG_PATH" ]]; then
  logger "Env var SAGEMAKER_RESOURCE_CONFIG_PATH is unset, trying to read from default location path"
  SAGEMAKER_RESOURCE_CONFIG_PATH="/opt/ml/config/resource_config.json"

  if [[ ! -f $SAGEMAKER_RESOURCE_CONFIG_PATH ]]; then
    logger "Env var SAGEMAKER_RESOURCE_CONFIG_PATH is unset and file does not exist: $SAGEMAKER_RESOURCE_CONFIG_PATH"
    logger "Assume vanilla cluster setup, no scripts to run. Exiting."
    exit 0
  fi
else
  logger "env var SAGEMAKER_RESOURCE_CONFIG_PATH is set to: $SAGEMAKER_RESOURCE_CONFIG_PATH"
  if [[ ! -f $SAGEMAKER_RESOURCE_CONFIG_PATH ]]; then
    logger "Env var SAGEMAKER_RESOURCE_CONFIG_PATH is set and file does not exist: $SAGEMAKER_RESOURCE_CONFIG_PATH"
    exit 1
  fi
fi

echo "Running lifecycle_script.py with resourceConfig: $SAGEMAKER_RESOURCE_CONFIG_PATH"

python3.9 -u lifecycle_script.py -rc $SAGEMAKER_RESOURCE_CONFIG_PATH 2>&1 | tee -a $LOG_FILE

exit_code=$?

exit $exit_code
