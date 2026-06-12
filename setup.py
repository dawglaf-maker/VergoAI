import sys
import platform
import subprocess
import os
import shutil
import glob
import importlib

def bootstrap():
    if os.environ.get("VERGOAI_BOOTSTRAP") == "1":
        return
    try:
        import jaraco.functools
        import wheel
    except ImportError:
        print("\nDetected missing core tools. Stabilizing environment...")
        os.environ["VERGOAI_BOOTSTRAP"] = "1"
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        print("Environment stabilized. Restarting setup...\n")
        subprocess.run([sys.executable] + sys.argv)
        sys.exit(0) 

if any(cmd in sys.argv for cmd in ["install", "develop"]):
    bootstrap()

from setuptools import setup, find_packages

def check_pytorch_status():
    """Returns 'cuda', 'cpu', or 'missing'."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", torch.__version__
        return "cpu", torch.__version__
    except ImportError:
        return "missing", None

def check_base_requirements(req_list):
    print("\nVerifying base requirements...")
    for req in req_list:
        pkg_name = req.split('>=')[0].split('<')[0].split('==')[0].strip().replace('-', '_')
        mapping = {"opencv_python": "cv2", "Pillow": "PIL"}
        import_name = mapping.get(pkg_name, pkg_name)
        try:
            importlib.import_module(import_name)
            print(f"  [OK] {req}")
        except ImportError:
            print(f"  [INSTALLING] {req}")

def get_gpu_info():
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader,nounits"], encoding='utf-8')
        cc = float(output.strip().split('\n')[0])
        return "nvidia", cc
    except:
        return "other", 0.0

def ask_user(prompt_text):
    print(f"{prompt_text} (Y/N): ", end='', flush=True)
    response = sys.stdin.readline().strip().lower()
    return response in ['y', 'yes']

# --- MAIN requires ---
install_requires = [
    "customtkinter>=5.2.0",
    "toml>=0.10.2",
    "Pillow>=10.0.0",
    "opencv-python>=4.8.0,<4.10.0",
    "requests>=2.31.0",
    "packaging>=23.1",
    "pyautogui>=0.9.54",
    "typing-extensions>=4.7.0",
    "ultralytics>=8.0.0",
    "numpy<2",
    "ninja",
]

setup(
    name="VergoAI",
    version="1.0.0",
    packages=find_packages(exclude=["api", "cfg", "images", "models", "tests", "typization"]),
    install_requires=install_requires,
)

if any(cmd in sys.argv for cmd in ["install", "develop"]):
    try:
        check_base_requirements(install_requires)
        
        # --- PYTORCH CHECK ---
        status, version = check_pytorch_status()
        gpu_type, cc = get_gpu_info()
        
        installed_pytorch = f"{status.upper()} Edition ({version})" if version else "Installing..."
        installed_cuda = "N/A"
        
        # Logic for NVIDIA users
        if gpu_type == "nvidia":
            if status == "cuda":
                print(f"\n[SKIP] PyTorch with CUDA is already installed ({version}).")
                installed_cuda = "Already Present"
            else:
                print(f"\nNVIDIA GPU detected (CC: {cc})")
                if ask_user("Do you want to install/upgrade to PyTorch FULL (CUDA Support)?"):
                    if cc >= 12.0 or cc == 10.0:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "--pre", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/nightly/cu128"])
                        installed_pytorch = "PyTorch (Nightly Full)"
                        installed_cuda = "12.8"
                    elif cc >= 8.9:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu124"])
                        installed_pytorch = "PyTorch (Stable Full)"
                        installed_cuda = "12.4"
                    else:
                        subprocess.check_call([sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu118"])
                        installed_pytorch = "PyTorch (Stable Full)"
                        installed_cuda = "11.8"
                elif status == "missing":
                    print("Installing PyTorch CPU Edition...")
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "torch", "torchvision"])
                    installed_pytorch = "PyTorch (Standard CPU)"
            
            subprocess.check_call([sys.executable, "-m", "pip", "install", "onnxruntime-gpu"])
            installed_onnx = "ONNX Runtime (GPU)"

        # Logic for Non-NVIDIA users
        else:
            if status != "missing":
                print(f"\n[SKIP] PyTorch is already installed ({version}).")
            else:
                print("\nInstalling mandatory PyTorch CPU...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "torch", "torchvision"])
                installed_pytorch = "PyTorch (Standard CPU)"
            
            subprocess.check_call([sys.executable, "-m", "pip", "install", "onnxruntime-directml"])
            installed_onnx = "ONNX Runtime (DirectML)"

        # Conflict Resolution
        subprocess.check_call([sys.executable, "-m", "pip", "install", "adbutils==2.12.0", "av==12.3.0"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", "git+https://github.com/leng-yue/py-scrcpy-client.git@v0.5.0"])
        
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n" + "="*50 + "\n              SETUP COMPLETED!                \n" + "="*50)
        print(f"  - PyTorch:          {installed_pytorch}\n  - CUDA Status:      {installed_cuda}\n  - ONNX Engine:      {installed_onnx}\n" + "="*50 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)