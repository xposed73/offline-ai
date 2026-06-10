import os
import sys
import shutil
import urllib.request
import subprocess
from pathlib import Path

# Ensure huggingface_hub is installed
try:
    import huggingface_hub
except ImportError:
    print("huggingface_hub package is not installed. Installing it now...")
    subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub"])
    try:
        import huggingface_hub
    except ImportError:
        print("Error: Could not install huggingface_hub. Please run 'pip install huggingface_hub' manually.")
        sys.exit(1)

# Paths
MODELS_DIR = Path("./models")
DATA_WHISPER_DIR = Path("./data/whisper")
RAGFLOW_DOCKER_DIR = Path("./ragflow/docker")

# 1. Create directories
print("Creating directories...")
MODELS_DIR.mkdir(parents=True, exist_ok=True)
DATA_WHISPER_DIR.mkdir(parents=True, exist_ok=True)
RAGFLOW_DOCKER_DIR.mkdir(parents=True, exist_ok=True)

# 2. Download RAGFlow configs
print("\n--- Downloading RAGFlow configuration files ---")
urls = {
    "infinity_conf.toml": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/infinity_conf.toml",
    "init.sql": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/init.sql",
    "entrypoint.sh": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/entrypoint.sh",
    "service_conf.yaml.template": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/service_conf.yaml.template"
}

for filename, url in urls.items():
    dest_path = RAGFLOW_DOCKER_DIR / filename
    if dest_path.exists():
        if dest_path.is_dir():
            shutil.rmtree(dest_path)
        else:
            print(f"{filename} already exists, will overwrite.")
    print(f"Downloading {filename} from {url}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")

# 3. Download LLM GGUF Model
print("\n--- Downloading Llama-cpp LLM Model (Qwen3-4B-Instruct) ---")
repo_id = "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF"
filename = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
try:
    print(f"Downloading {filename} from Hugging Face...")
    huggingface_hub.hf_hub_download(repo_id=repo_id, filename=filename, local_dir=str(MODELS_DIR))
    print(f"Successfully downloaded GGUF model to {MODELS_DIR / filename}")
except Exception as e:
    print(f"Failed to download GGUF model: {e}")

# 4. Create active_model.conf configuration
conf_path = MODELS_DIR / "active_model.conf"
if not conf_path.exists():
    print(f"Creating active model configuration: {conf_path}")
    try:
        with open(conf_path, "w", newline='\n') as f:
            f.write(f"LLAMA_HF_REPO={repo_id}\n")
            f.write(f"LLAMA_HF_FILE={filename}\n")
    except Exception as e:
        print(f"Failed to write configuration: {e}")

# 5. Download Whisper model
print("\n--- Downloading Speaches Whisper Model (faster-whisper-small) ---")
try:
    print("Downloading snapshot...")
    huggingface_hub.snapshot_download(repo_id="Systran/faster-whisper-small", cache_dir=str(DATA_WHISPER_DIR))
    print("Successfully downloaded Whisper model snapshot")
except Exception as e:
    print(f"Failed to download Whisper model snapshot: {e}")

# 6. Download default English Voice model
print("\n--- Downloading Speaches English Kokoro Model (Kokoro-82M-v1.0-ONNX) ---")
try:
    print("Downloading snapshot...")
    huggingface_hub.snapshot_download(repo_id="speaches-ai/Kokoro-82M-v1.0-ONNX", cache_dir=str(DATA_WHISPER_DIR))
    print("Successfully downloaded English voice model snapshot")
except Exception as e:
    print(f"Failed to download English voice model snapshot: {e}")

# 7. Download German Voice Model (Godelaune/Kokoro-82M-ONNX-German-Martin)
print("\n--- Downloading Speaches German Kokoro Model (Kokoro-82M-ONNX-German-Martin) ---")
try:
    print("Downloading snapshot...")
    cache_dir = huggingface_hub.snapshot_download(repo_id="Godelaune/Kokoro-82M-ONNX-German-Martin", cache_dir=str(DATA_WHISPER_DIR))
    print(f"Snapshot downloaded to: {cache_dir}")
    
    snapshot_path = Path(cache_dir)
    onnx_src = snapshot_path / "kokoro-martin.onnx"
    onnx_dst = snapshot_path / "model.onnx"
    npz_src = snapshot_path / "voices-martin.npz"
    npz_dst = snapshot_path / "voices.bin"
    
    if onnx_src.exists() and not onnx_dst.exists():
        print(f"Creating copy for {onnx_dst}...")
        shutil.copy(onnx_src, onnx_dst)
    if npz_src.exists() and not npz_dst.exists():
        print(f"Creating copy for {npz_dst}...")
        shutil.copy(npz_src, npz_dst)
        
    readme_path = snapshot_path / "README.md"
    if readme_path.exists():
        print("Patching README.md tags...")
        content = readme_path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                front_matter = parts[1]
                body = parts[2]
                lines = front_matter.splitlines()
                has_tags = False
                has_library_name = False
                tags_index = -1
                for i, line in enumerate(lines):
                    if line.strip().startswith("tags:"):
                        has_tags = True
                        tags_index = i
                    elif line.strip().startswith("library_name:"):
                        has_library_name = True
                if has_tags:
                    insert_idx = tags_index + 1
                    lines.insert(insert_idx, "- speaches")
                    lines.insert(insert_idx + 1, "- kokoro")
                else:
                    lines.append("tags:")
                    lines.append("- speaches")
                    lines.append("- kokoro")
                if not has_library_name:
                    lines.append("library_name: onnx")
                new_front_matter = "\n".join(lines)
                new_content = f"---\n{new_front_matter}\n---\n{body}"
                readme_path.write_text(new_content, encoding="utf-8")
                print("README.md patched successfully!")
                
    # Delete nested README.md files to prevent Speaches parsing collision
    for sub in ["wyoming_openai_german_separator", "onnx-docker"]:
        nested_readme = snapshot_path / sub / "README.md"
        if nested_readme.exists():
            print(f"Removing nested readme to prevent collision: {nested_readme}")
            nested_readme.unlink()
except Exception as e:
    print(f"Failed to download or configure German voice model: {e}")

# 8. Generate patched Speaches utils
print("\n--- Generating Patched Speaches Utils ---")
original_utils_path = Path("./scratch/original_utils.py")
patched_utils_path = DATA_WHISPER_DIR / "patched_utils.py"

if not original_utils_path.exists():
    print(f"Error: Original utils script not found at {original_utils_path}. Cannot generate patched_utils.py.")
else:
    try:
        content = original_utils_path.read_text(encoding="utf-8")
        if 'KokoroModelVoice(name="martin"' in content:
            print("Original utils already contain martin voice metadata, writing directly.")
            patched_content = content
        else:
            print("Injecting martin voice metadata into VOICES list...")
            target_str = '    # American English'
            replacement_str = '    # German\n    KokoroModelVoice(name="martin", language="de", gender="male"),\n\n    # American English'
            if target_str in content:
                patched_content = content.replace(target_str, replacement_str, 1)
            else:
                print("Warning: '# American English' placeholder not found. Appending martin voice at start of VOICES list.")
                # Fallback replacement after VOICES = [
                patched_content = content.replace("VOICES = [", 'VOICES = [\n    KokoroModelVoice(name="martin", language="de", gender="male"),', 1)
        
        patched_utils_path.write_text(patched_content, encoding="utf-8")
        print(f"Successfully wrote patched utils to {patched_utils_path}")
    except Exception as e:
        print(f"Failed to generate patched utils: {e}")

print("\nInstallation/Setup completed! You can now start the stack with 'docker compose up -d'.")
