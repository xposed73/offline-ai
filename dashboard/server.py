import os
import json
import socket
import urllib.request
import urllib.parse
import urllib.error
import threading
import time
import sqlite3
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

# ---------------------------------------------------------------------------
# Open WebUI admin API key (auto-read from webui.db)
# ---------------------------------------------------------------------------
_cached_api_key = None
_api_key_lock = threading.Lock()

def get_openwebui_api_key():
    """Read the first admin user's API key from the Open WebUI SQLite database."""
    global _cached_api_key
    with _api_key_lock:
        if _cached_api_key:
            return _cached_api_key
        db_path = "/workspace/data/open-webui/webui.db"
        if not os.path.exists(db_path):
            return None
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # Try the api_key column on the user table (Open WebUI >= 0.3)
            cur.execute(
                "SELECT api_key FROM user WHERE role='admin' AND api_key IS NOT NULL AND api_key != '' LIMIT 1"
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                _cached_api_key = row[0]
                return _cached_api_key
        except Exception as e:
            print("get_openwebui_api_key error:", e)
        return None

def openwebui_request(method, path, body=None, content_type="application/json", extra_headers=None):
    """Make an authenticated request to the Open WebUI internal API."""
    api_key = get_openwebui_api_key()
    if not api_key:
        raise RuntimeError("Open WebUI admin API key not found. Log into Open WebUI at :3000 first to generate your account.")
    url = f"http://open-webui:8080{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Dashboard/1.0",
    }
    if content_type:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    if body and isinstance(body, dict):
        body = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or '{"detail": "HTTP Error"}')
    except Exception as e:
        raise RuntimeError(str(e))

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
                "qdrant": ping_service("http://qdrant:6333/")
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

        # API: List Knowledge Bases
        elif self.path == "/api/knowledge/list":
            try:
                status, data = openwebui_request("GET", "/api/v1/knowledge/")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
            except Exception as e:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
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

        # API: Create a Knowledge Base
        elif self.path == "/api/knowledge/create":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode('utf-8'))
                name = payload.get("name", "").strip()
                description = payload.get("description", "").strip()
                if not name:
                    self._send_json(400, {"error": "name is required"})
                    return
                status, data = openwebui_request("POST", "/api/v1/knowledge/create", {
                    "name": name,
                    "description": description,
                    "data": {}
                })
                self._send_json(status, data)
            except Exception as e:
                self._send_json(503, {"error": str(e)})
            return

        # API: Upload a PDF to a Knowledge Base
        elif self.path == "/api/knowledge/upload":
            try:
                content_type = self.headers.get("Content-Type", "")
                content_length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(content_length)

                # Parse multipart boundary
                boundary = None
                for part in content_type.split(";"):
                    part = part.strip()
                    if part.startswith("boundary="):
                        boundary = part[len("boundary="):].strip().encode()
                        break
                if not boundary:
                    self._send_json(400, {"error": "No multipart boundary found"})
                    return

                # Split parts
                parts = raw_body.split(b"--" + boundary)
                fields = {}
                file_data = None
                file_name = "upload.pdf"

                for part in parts[1:]:
                    if part in (b"--\r\n", b"--", b"\r\n"):
                        continue
                    header_end = part.find(b"\r\n\r\n")
                    if header_end == -1:
                        continue
                    header_section = part[:header_end].decode("utf-8", errors="replace")
                    body_section = part[header_end + 4:]
                    # Strip trailing \r\n
                    if body_section.endswith(b"\r\n"):
                        body_section = body_section[:-2]

                    # Parse Content-Disposition
                    disposition = ""
                    for line in header_section.splitlines():
                        if line.lower().startswith("content-disposition:"):
                            disposition = line
                    name_val = ""
                    filename_val = ""
                    for token in disposition.split(";"):
                        token = token.strip()
                        if token.startswith("name="):
                            name_val = token[5:].strip('"')
                        elif token.startswith("filename="):
                            filename_val = token[9:].strip('"')

                    if filename_val:
                        file_data = body_section
                        file_name = filename_val
                    else:
                        fields[name_val] = body_section.decode("utf-8", errors="replace")

                knowledge_id = fields.get("knowledge_id", "").strip()
                if not knowledge_id:
                    self._send_json(400, {"error": "knowledge_id field is required"})
                    return
                if file_data is None:
                    self._send_json(400, {"error": "No PDF file found in request"})
                    return

                # Step 1: Upload the file to Open WebUI /files/
                api_key = get_openwebui_api_key()
                if not api_key:
                    self._send_json(503, {"error": "Open WebUI admin API key not found. Please log into Open WebUI at :3000 first."})
                    return

                # Build multipart body to forward to Open WebUI
                bound = b"DashboardBoundary1234567890"
                mpart = b"--" + bound + b"\r\n"
                mpart += f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode()
                mpart += b"Content-Type: application/pdf\r\n\r\n"
                mpart += file_data + b"\r\n"
                mpart += b"--" + bound + b"--\r\n"

                upload_url = "http://open-webui:8080/api/v1/files/"
                upload_req = urllib.request.Request(
                    upload_url,
                    data=mpart,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": f"multipart/form-data; boundary={bound.decode()}",
                        "User-Agent": "Dashboard/1.0",
                    },
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(upload_req, timeout=60) as resp:
                        file_resp = json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    err_body = e.read().decode("utf-8", errors="replace")
                    self._send_json(e.code, {"error": f"File upload failed: {err_body}"})
                    return

                file_id = file_resp.get("id")
                if not file_id:
                    self._send_json(500, {"error": "Open WebUI did not return a file ID", "detail": file_resp})
                    return

                # Step 2: Add the file to the Knowledge Base
                status, kb_resp = openwebui_request(
                    "POST",
                    f"/api/v1/knowledge/{knowledge_id}/file/add",
                    {"file_id": file_id}
                )
                self._send_json(status, {"status": "ok" if status == 200 else "error", "file_id": file_id, "detail": kb_resp})
            except Exception as e:
                import traceback
                print("Knowledge upload error:", traceback.format_exc())
                self._send_json(500, {"error": str(e)})
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
