#!/usr/bin/env bash
# Installs the free talking-head engine (SadTalker, CPU) into ./.presenter (cached between runs).
set -e
ROOT="$(pwd)/.presenter"
mkdir -p "$ROOT"
cd "$ROOT"
if [ ! -d SadTalker ]; then
  git clone -q --depth 1 https://github.com/OpenTalker/SadTalker.git
fi
if [ ! -x venv/bin/python ]; then
  python3.10 -m venv venv
fi
. venv/bin/activate
pip install -q --upgrade pip
pip install -q torch==2.1.2 torchvision==0.16.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cpu
pip install -q numpy==1.23.5 face_alignment==1.3.5 imageio==2.19.3 imageio-ffmpeg==0.4.7 librosa==0.9.2 \
  numba resampy==0.3.1 pydub==0.25.1 scipy==1.10.1 kornia==0.6.8 tqdm yacs==0.1.8 pyyaml joblib==1.1.0 \
  scikit-image==0.19.3 basicsr==1.4.2 facexlib==0.3.0 gfpgan==1.3.8 av safetensors opencv-python-headless==4.8.1.78
cd SadTalker
mkdir -p checkpoints gfpgan/weights
dl() { [ -s "$2" ] || curl -sSL --retry 3 -o "$2" "$1"; }
R=https://github.com/OpenTalker/SadTalker/releases/download/v0.0.2-rc
dl $R/mapping_00109-model.pth.tar checkpoints/mapping_00109-model.pth.tar
dl $R/mapping_00229-model.pth.tar checkpoints/mapping_00229-model.pth.tar
dl $R/SadTalker_V0.0.2_256.safetensors checkpoints/SadTalker_V0.0.2_256.safetensors
dl $R/SadTalker_V0.0.2_512.safetensors checkpoints/SadTalker_V0.0.2_512.safetensors
dl https://github.com/xinntao/facexlib/releases/download/v0.1.0/alignment_WFLW_4HG.pth gfpgan/weights/alignment_WFLW_4HG.pth
dl https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth gfpgan/weights/detection_Resnet50_Final.pth
dl https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth gfpgan/weights/GFPGANv1.4.pth
dl https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth gfpgan/weights/parsing_parsenet.pth
ls -la checkpoints gfpgan/weights
echo "presenter engine ready"
