#!/bin/bash

set -exo pipefail

echo "
###################################
# BEGIN: install containerd
###################################
"

apt-get -y -q -o DPkg::Lock::Timeout=120 update
apt-get -y -q -o DPkg::Lock::Timeout=120 install containerd
systemctl enable containerd.service
systemctl start containerd.service

# install nvidia docker toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get install -q -y -o DPkg::Lock::Timeout=120 nvidia-container-toolkit