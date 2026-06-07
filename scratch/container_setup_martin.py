import os
import shutil
import huggingface_hub
from pathlib import Path

repo_id = "Godelaune/Kokoro-82M-ONNX-German-Martin"
print(f"Downloading snapshot for {repo_id}...")
cache_dir = huggingface_hub.snapshot_download(repo_id=repo_id, cache_dir="c:/Users/root/Desktop/offline-ai/data/whisper")
print(f"Snapshot downloaded to: {cache_dir}")

snapshot_path = Path(cache_dir)
onnx_src = snapshot_path / "kokoro-martin.onnx"
onnx_dst = snapshot_path / "model.onnx"

npz_src = snapshot_path / "voices-martin.npz"
npz_dst = snapshot_path / "voices.bin"

if onnx_src.exists() and not onnx_dst.exists():
    print(f"Creating symlink/copy for {onnx_dst}...")
    shutil.copy(onnx_src, onnx_dst)

if npz_src.exists() and not npz_dst.exists():
    print(f"Creating symlink/copy for {npz_dst}...")
    shutil.copy(npz_src, npz_dst)

readme_path = snapshot_path / "README.md"
if readme_path.exists():
    print("Patching README.md tags...")
    content = readme_path.read_text(encoding="utf-8")
    
    # Let's check if we have the front matter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            front_matter = parts[1]
            body = parts[2]
            
            # We want to ensure tags: has 'speaches' and 'kokoro'
            # Let's parse/modify it simple way
            lines = front_matter.splitlines()
            has_tags = False
            tags_index = -1
            for i, line in enumerate(lines):
                if line.strip().startswith("tags:"):
                    has_tags = True
                    tags_index = i
                    break
            
            if has_tags:
                # Add tags to the list
                # Check if tags is list style
                insert_idx = tags_index + 1
                lines.insert(insert_idx, "- speaches")
                lines.insert(insert_idx + 1, "- kokoro")
            else:
                lines.append("tags:")
                lines.append("- speaches")
                lines.append("- kokoro")
                
            new_front_matter = "\n".join(lines)
            new_content = f"---{new_front_matter}---{body}"
            readme_path.write_text(new_content, encoding="utf-8")
            print("README.md patched successfully!")
else:
    print("README.md not found in snapshot!")
