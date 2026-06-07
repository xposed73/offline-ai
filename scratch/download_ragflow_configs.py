import urllib.request
import os
import shutil

urls = {
    "infinity_conf.toml": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/infinity_conf.toml",
    "init.sql": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/init.sql",
    "entrypoint.sh": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/entrypoint.sh",
    "service_conf.yaml.template": "https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/service_conf.yaml.template"
}

dest_dir = "ragflow/docker"

for filename, url in urls.items():
    dest_path = os.path.join(dest_dir, filename)
    
    # If the path exists as a directory, remove it
    if os.path.exists(dest_path):
        if os.path.isdir(dest_path):
            print(f"Removing directory: {dest_path}")
            shutil.rmtree(dest_path)
        else:
            print(f"File already exists: {dest_path}, will overwrite")
            
    print(f"Downloading {url} to {dest_path}...")
    try:
        urllib.request.urlretrieve(url, dest_path)
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")
