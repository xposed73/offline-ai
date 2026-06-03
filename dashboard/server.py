import os
import json
import socket
import urllib.request
import urllib.parse
import urllib.error
import threading
import time
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Preconfigured popular models
POPULAR_MODELS = [
    {
        "id": "qwen-3-4b",
        "name": "Qwen 3 4B Instruct (Recommended)",
        "repo": "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF",
        "file": "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
        "size": "2.5 GB"
    },
    {
        "id": "llama-3.2-3b",
        "name": "Llama 3.2 3B Instruct",
        "repo": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "file": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size": "2.0 GB"
    },
    {
        "id": "phi-3.5-mini",
        "name": "Phi-3.5 Mini Instruct",
        "repo": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "file": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size": "2.6 GB"
    },
    {
        "id": "qwen-2.5-0.5b",
        "name": "Qwen 2.5 0.5B Instruct (Lightweight)",
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size": "398 MB"
    }
]

# Global download status
download_status = {
    "active": False,
    "repo": "",
    "file": "",
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "speed": "0 KB/s",
    "percent": 0,
    "error": None
}




def is_model_downloaded(repo, filename):
    # Check flat file first
    flat_path = os.path.join("/workspace/models", filename)
    if os.path.isfile(flat_path) and os.path.getsize(flat_path) > 100 * 1024 * 1024:
        return True
    
    # Check HF cache directory structure
    if repo:
        repo_folder = f"models--{repo.replace('/', '--')}"
        repo_path = os.path.join("/workspace/models", repo_folder)
        if os.path.isdir(repo_path):
            blobs_path = os.path.join(repo_path, "blobs")
            if os.path.isdir(blobs_path):
                for f in os.listdir(blobs_path):
                    if not f.endswith(".downloadInProgress") and not f.endswith(".incomplete"):
                        full_f = os.path.join(blobs_path, f)
                        if os.path.isfile(full_f) and os.path.getsize(full_f) > 100 * 1024 * 1024:
                            return True
    return False

def read_env():
    conf_path = "/workspace/models/active_model.conf"
    values = {"LLAMA_HF_REPO": "", "LLAMA_HF_FILE": ""}
    if os.path.exists(conf_path):
        try:
            with open(conf_path, "r") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.split("=", 1)
                        values[k.strip()] = v.strip()
        except Exception as e:
            print("Failed to read active_model.conf:", e)
    
    # Fallback default values if not defined
    if not values.get("LLAMA_HF_FILE"):
        values["LLAMA_HF_REPO"] = "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF"
        values["LLAMA_HF_FILE"] = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    return values

def update_env(repo, filename):
    conf_path = "/workspace/models/active_model.conf"
    try:
        os.makedirs(os.path.dirname(conf_path), exist_ok=True)
        with open(conf_path, "w") as f:
            f.write(f"LLAMA_HF_REPO={repo}\n")
            f.write(f"LLAMA_HF_FILE={filename}\n")
        return True
    except Exception as e:
        print("Failed to write active_model.conf:", e)
        return False

def restart_llama_cpp():
    if not os.path.exists('/var/run/docker.sock'):
        print("Docker socket not found at /var/run/docker.sock")
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect('/var/run/docker.sock')
        # Send HTTP POST to Docker API to restart llama-cpp
        request = "POST /v1.41/containers/llama-cpp/restart HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        s.sendall(request.encode('utf-8'))
        response = s.recv(1024).decode('utf-8')
        s.close()
        print("Docker restart response:", response)
        return "204 No Content" in response or "200 OK" in response
    except Exception as e:
        print("Failed to restart container:", e)
        return False

def download_worker(repo, filename):
    global download_status
    download_status["active"] = True
    download_status["repo"] = repo
    download_status["file"] = filename
    download_status["downloaded_bytes"] = 0
    download_status["total_bytes"] = 0
    download_status["percent"] = 0
    download_status["error"] = None
    
    url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
    dest_path = os.path.join("/workspace/models", filename)
    temp_path = dest_path + ".downloadInProgress"
    
    try:
        os.makedirs("/workspace/models", exist_ok=True)
        print(f"Starting download from: {url}")
        
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            total_size = int(response.headers.get('content-length', 0))
            download_status["total_bytes"] = total_size
            
            chunk_size = 1024 * 1024  # 1MB
            downloaded = 0
            start_time = time.time()
            last_progress_time = start_time
            last_downloaded = 0
            
            with open(temp_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    download_status["downloaded_bytes"] = downloaded
                    
                    if total_size > 0:
                        download_status["percent"] = int((downloaded / total_size) * 100)
                    
                    now = time.time()
                    elapsed = now - last_progress_time
                    if elapsed >= 1.0:
                        speed_bps = (downloaded - last_downloaded) / elapsed
                        if speed_bps > 1024 * 1024:
                            download_status["speed"] = f"{speed_bps / (1024*1024):.2f} MB/s"
                        else:
                            download_status["speed"] = f"{speed_bps / 1024:.2f} KB/s"
                        last_progress_time = now
                        last_downloaded = downloaded
            
            if os.path.exists(dest_path):
                os.remove(dest_path)
            os.rename(temp_path, dest_path)
            print("Download completed successfully!")
            download_status["active"] = False
            
    except Exception as e:
        print(f"Download failed: {e}")
        download_status["error"] = str(e)
        download_status["active"] = False
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def ping_service(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=1.0) as response:
                return True
        except urllib.error.HTTPError as e:
            # 503 (loading model), 401/403/404 are still active servers
            return e.code in [200, 204, 302, 401, 403, 404, 503]
    except Exception:
        return False

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        # API: Get status of all containers
        if self.path == "/api/status":
            status = {
                "webui": ping_service("http://open-webui:8080/"),
                "whisper": ping_service("http://whisper:9000/"),
                "llamacpp": ping_service("http://llama-cpp:8080/health"),
                "qdrant": ping_service("http://qdrant:6333/"),
                "ragflow": ping_service("http://host.docker.internal:8000/")
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode('utf-8'))
            return

        # API: List GGUF models
        elif self.path == "/api/models":
            env = read_env()
            active_repo = env.get("LLAMA_HF_REPO", "")
            active_file = env.get("LLAMA_HF_FILE", "")
            
            models_list = []
            
            # Add popular presets
            for m in POPULAR_MODELS:
                downloaded = is_model_downloaded(m["repo"], m["file"])
                is_active = (m["file"] == active_file) and (not active_repo or m["repo"] == active_repo)
                models_list.append({
                    "id": m["id"],
                    "name": m["name"],
                    "repo": m["repo"],
                    "file": m["file"],
                    "size": m["size"],
                    "downloaded": downloaded,
                    "active": is_active,
                    "preset": True
                })
            
            # Scan for other custom GGUF files in /workspace/models
            if os.path.isdir("/workspace/models"):
                for f in os.listdir("/workspace/models"):
                    if f.endswith(".gguf") and not f.endswith(".downloadInProgress"):
                        is_preset = any(pm["file"] == f for pm in POPULAR_MODELS)
                        if not is_preset:
                            is_active = (f == active_file) and not active_repo
                            size_bytes = os.path.getsize(os.path.join("/workspace/models", f))
                            size_str = f"{size_bytes / (1024*1024*1024):.2f} GB" if size_bytes > 1024*1024*1024 else f"{size_bytes / (1024*1024):.1f} MB"
                            models_list.append({
                                "id": f.lower().replace(".", "-"),
                                "name": f,
                                "repo": "",
                                "file": f,
                                "size": size_str,
                                "downloaded": True,
                                "active": is_active,
                                "preset": False
                            })
                            
            response_data = {
                "active_repo": active_repo,
                "active_file": active_file,
                "models": models_list
            }
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode('utf-8'))
            return
            
        # API: Get download progress status
        elif self.path == "/api/download/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(download_status).encode('utf-8'))
            return

        # API: Query loaded voice models from Speaches
        elif self.path == "/api/voice/models":
            try:
                req = urllib.request.Request("http://whisper:9000/v1/models", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode('utf-8'))
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return



        # Serve static files normally
        super().do_GET()

    def do_POST(self):
        # API: Start model download
        if self.path == "/api/download":
            if download_status["active"]:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "A download is already in progress"}).encode('utf-8'))
                return
                
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode('utf-8'))
            
            repo = payload.get("repo", "").strip()
            filename = payload.get("file", "").strip()
            
            if not repo or not filename:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Both repo and file are required"}).encode('utf-8'))
                return
                
            # Launch downloader in a background thread
            t = threading.Thread(target=download_worker, args=(repo, filename))
            t.daemon = True
            t.start()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode('utf-8'))
            return
            
        # API: Activate a model (write to env and restart container)
        elif self.path == "/api/activate":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode('utf-8'))
            
            repo = payload.get("repo", "").strip()
            filename = payload.get("file", "").strip()
            
            if not filename:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Filename is required"}).encode('utf-8'))
                return
                
            # Update active_model.conf configuration
            success_env = update_env(repo, filename)
            if not success_env:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Failed to update configuration file"}).encode('utf-8'))
                return
                
            # Restart llama-cpp container
            success_restart = restart_llama_cpp()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "success",
                "env_updated": success_env,
                "container_restarted": success_restart
            }).encode('utf-8'))
            return

        # API: Trigger download of voice model in Speaches
        elif self.path == "/api/voice/download":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            payload = json.loads(post_data.decode('utf-8'))
            model_id = payload.get("model_id", "").strip()
            
            if not model_id:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "model_id is required"}).encode('utf-8'))
                return
                
            def trigger_voice_download(m_id):
                try:
                    import urllib.parse
                    encoded_model_id = urllib.parse.quote(m_id, safe="")
                    url = f"http://whisper:9000/v1/models/{encoded_model_id}"
                    req = urllib.request.Request(url, data=b"", headers={"User-Agent": "Mozilla/5.0"}, method="POST")
                    with urllib.request.urlopen(req, timeout=600) as response:
                        print(f"Speaches download complete for {m_id}: {response.read().decode('utf-8')}")
                except Exception as e:
                    print(f"Failed to download voice model {m_id}: {e}")
                    
            t = threading.Thread(target=trigger_voice_download, args=(model_id,))
            t.daemon = True
            t.start()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode('utf-8'))
            return



        self.send_response(404)
        self.end_headers()

    def _send_json(self, status, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server_address = ('', 80)
    httpd = ThreadingHTTPServer(server_address, DashboardHandler)
    print("Dashboard Python server running on port 80...")
    httpd.serve_forever()
