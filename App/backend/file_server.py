from typing import Dict
import weakref
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QFileDialog
import sys
from fastapi.responses import PlainTextResponse
from fastapi.responses import JSONResponse
import json
import asyncio
import subprocess
import signal
from keyword_extractor import extract_keywords
import math

app = FastAPI()
qt_app = QApplication(sys.argv)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Filename", "X-Full-Path"],  # Explicitly expose our custom headers
)

class FileInfo(BaseModel):
    id: str
    name: str
    path: str
    type: str  # 'file' or 'directory'
    content: str | None = None
    parentId: str | None = None

class SaveFileRequest(BaseModel):
    path: str
    content: str

class CreateFileRequest(BaseModel):
    parentId: str
    name: str

class CreateDirectoryRequest(BaseModel):
    parentId: str
    name: str

class PathRequest(BaseModel):
    path: str

class RenameRequest(BaseModel):
    path: str
    new_name: str

class InsertCodeRequest(BaseModel):
    path: str
    content: str
    position: int | None = None  # Optional cursor position for future use

class RelevantFilesRequest(BaseModel):
    query: str
    max_files: int = 10
    include_content: bool = True

base_directory: str | None = None  # Initialize as None instead of os.getcwd()

# Add a file cache to track open files
file_cache: Dict[str, str] = {}

def is_text_file(filename: str) -> bool:
    """Check if a file is a text file based on its extension."""
    text_extensions = {
        'txt', 'js', 'jsx', 'ts', 'tsx', 'md', 'json', 'html', 'css', 'scss',
        'less', 'xml', 'svg', 'yaml', 'yml', 'ini', 'conf', 'sh', 'bash', 'py',
        'java', 'cpp', 'c', 'h', 'hpp', 'rs', 'go', 'rb', 'php', 'sql', 'vue',
        'gitignore', 'env', 'editorconfig'
    }
    return Path(filename).suffix.lstrip('.').lower() in text_extensions

def generate_id(prefix: str, path: str) -> str:
    """Generate a unique ID for a file or directory."""
    # Only sanitize the path part, not the filename
    base_name = os.path.basename(path)
    dir_path = os.path.dirname(path)
    sanitized_dir = "_".join(c if c.isalnum() else "_" for c in dir_path)
    return f"{prefix}_{sanitized_dir}_{base_name}" if sanitized_dir else f"{prefix}_{base_name}"

def scan_directory(path: str, parent_id: str | None = None) -> dict:
    """Scan a directory and return its contents."""
    items = {}
    
    try:
        # Create root item first
        root_path = Path(path)
        root_id = generate_id('root', str(root_path))
        
        try:
            relative_to_base = os.path.relpath(path, base_directory)
        except ValueError:
            relative_to_base = root_path.name

        # Use the actual folder name for the root
        folder_name = os.path.basename(path)
        if not folder_name:  # If path ends with a slash
            folder_name = os.path.basename(os.path.dirname(path))

        items[root_id] = FileInfo(
            id=root_id,
            name=folder_name,
            type='directory',
            path=relative_to_base,
            parentId=parent_id
        )

        entries = sorted(Path(path).iterdir())
        for entry in entries:
            # Skip hidden files
            if entry.name.startswith('.'):
                continue

            relative_path = os.path.relpath(str(entry), base_directory)
            entry_id = generate_id(
                'dir' if entry.is_dir() else 'file',
                relative_path
            )
            
            if entry.is_dir():
                items[entry_id] = FileInfo(
                    id=entry_id,
                    name=entry.name,
                    path=relative_path,
                    type='directory',
                    parentId=root_id
                )
            else:
                content = None
                if is_text_file(entry.name):
                    try:
                        if entry.stat().st_size <= 1024 * 1024:  # 1MB limit
                            try:
                                # Don't keep file handle open
                                with open(str(entry), 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()
                                # Add to cache
                                file_cache[str(entry)] = content
                            except UnicodeDecodeError as ude:
                                print(f"Unicode decode error for {entry}: {str(ude)}")
                                content = '[Error: File encoding not supported]'
                            except PermissionError as pe:
                                print(f"Permission error reading {entry}: {str(pe)}")
                                content = '[Error: Permission denied]'
                            except OSError as oe:
                                print(f"OS error reading {entry}: {str(oe)}")
                                content = f'[Error: OS Error - {str(oe)}]'
                            except Exception as e:
                                print(f"Unexpected error reading {entry}: {type(e).__name__} - {str(e)}")
                                content = f'[Error reading file: {type(e).__name__} - {str(e)}]'
                        else:
                            content = '[File too large to display]'
                    except Exception as e:
                        print(f"Error accessing file {entry}: {type(e).__name__} - {str(e)}")
                        content = f'[Error: {type(e).__name__} - {str(e)}]'
                else:
                    content = '[Binary file]'

                items[entry_id] = FileInfo(
                    id=entry_id,
                    name=entry.name,
                    path=relative_path,
                    type='file',
                    content=content,
                    parentId=root_id
                )

    except Exception as e:
        print(f"Error in scan_directory: {type(e).__name__} - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "items": items,
        "rootId": root_id,
        "path": path
    }

@app.post("/open-directory")
async def open_directory():
    """Open a directory using dialog and return its contents."""
    global base_directory
    
    dialog = QFileDialog()
    dialog.setFileMode(QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    
    if dialog.exec_():
        folders = dialog.selectedFiles()
        if not folders:
            raise HTTPException(status_code=400, detail="No directory selected")
        
        path = folders[0]
        base_directory = path
        return scan_directory(path)
    
    raise HTTPException(status_code=400, detail="No directory selected")

@app.get("/read-directory")
async def read_directory(path: str):
    """Read contents of a specific directory."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    full_path = os.path.join(base_directory, path)
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Directory not found")
    if not os.path.isdir(full_path):
        raise HTTPException(status_code=400, detail="Path is not a directory")

    return scan_directory(full_path)

@app.post("/save-file")
async def save_file(request: SaveFileRequest):
    """Save content to a file."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        full_path = os.path.abspath(os.path.join(base_directory, request.path))
        print(f"Saving file to: {full_path}")
        
        # Security check - make sure the path is within base directory
        if not full_path.startswith(base_directory):
            raise HTTPException(status_code=403, detail="Access denied")

        # Create directories if they don't exist
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        with open(full_path.replace('file_', ''), 'w', encoding='utf-8') as f:
            f.write(request.content)

        # Update the cache if the file is cached
        if full_path in file_cache:
            file_cache[full_path] = request.content

        return {'success': True}
    except Exception as e:
        print(f"Error saving file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-file")
async def create_file(request: CreateFileRequest):
    """Create a new file."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        # Get parent path from parentId
        parent_path = ""
        if not request.parentId.startswith('root_'):
            # Find the parent item to get its path
            for entry in Path(base_directory).rglob('*'):
                if entry.is_dir():
                    entry_id = generate_id('dir', os.path.relpath(str(entry), base_directory))
                    if entry_id == request.parentId:
                        parent_path = os.path.relpath(str(entry), base_directory)
                        break
        
        # Create the full path for the new file
        full_path = os.path.join(base_directory, parent_path, request.name)
        
        if os.path.exists(full_path):
            raise HTTPException(status_code=400, detail="File already exists")

        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Create empty file
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write('')

        # Generate response with file info
        relative_path = os.path.relpath(full_path, base_directory)
        file_id = generate_id('file', relative_path)
        
        file_info = FileInfo(
            id=file_id,
            name=request.name,
            path=relative_path,
            type='file',
            content='',
            parentId=request.parentId
        )

        return {
            "id": file_id,
            "file": file_info
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-directory")
async def create_directory(request: CreateDirectoryRequest):
    """Create a new directory."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        # Get parent path from parentId
        parent_path = ""
        if not request.parentId.startswith('root_'):
            # Find the parent item to get its path
            for entry in Path(base_directory).rglob('*'):
                if entry.is_dir():
                    entry_id = generate_id('dir', os.path.relpath(str(entry), base_directory))
                    if entry_id == request.parentId:
                        parent_path = os.path.relpath(str(entry), base_directory)
                        break
        
        # Create the full path for the new directory
        full_path = os.path.join(base_directory, parent_path, request.name)
        
        if os.path.exists(full_path):
            raise HTTPException(status_code=400, detail="Directory already exists")

        # Create the directory
        os.makedirs(full_path)

        # Generate response with directory info
        relative_path = os.path.relpath(full_path, base_directory)
        dir_id = generate_id('dir', relative_path)
        
        dir_info = FileInfo(
            id=dir_id,
            name=request.name,
            path=relative_path,
            type='directory',
            parentId=request.parentId
        )

        return {
            "id": dir_id,
            "directory": dir_info
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete")
@app.post("/delete")
async def delete_item(request: PathRequest):
    """Delete a file or directory."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        full_path = os.path.abspath(os.path.join(base_directory, request.path))
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="Path not found")

        # Clear any cached references to files we're about to delete
        if os.path.isdir(full_path):
            # Clear cache for all files in directory
            for cached_path in list(file_cache.keys()):
                if cached_path.startswith(full_path):
                    del file_cache[cached_path]
        else:
            # Clear cache for single file
            if full_path in file_cache:
                del file_cache[full_path]

        # Force garbage collection
        import gc
        gc.collect()

        if os.path.isdir(full_path):
            import shutil
            shutil.rmtree(full_path, ignore_errors=True)
        else:
            os.remove(full_path)

        return {'success': True}
            
    except Exception as e:
        print(f"Error in delete_item: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/open-specific-directory")
async def open_specific_directory(request: PathRequest):
    """Open a specific directory path."""
    global base_directory
    
    if not request.path:
        raise HTTPException(status_code=400, detail="No directory path provided")
        
    if not os.path.exists(request.path):
        raise HTTPException(status_code=404, detail="Directory not found")
    if not os.path.isdir(request.path):
        raise HTTPException(status_code=400, detail="Path is not a directory")
    
    base_directory = os.path.abspath(request.path)
    print(f"Set base directory to: {base_directory}")
    return scan_directory(request.path)

@app.post("/fetch-folder-contents")
async def fetch_folder_contents(request: PathRequest):
    """Fetch contents of a specific folder."""
    global base_directory
    
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened. Please open a directory first.")

    # Handle empty path as root directory
    if not request.path:
        return scan_directory(base_directory)
        
    target_path = os.path.join(base_directory, request.path)
    print(f"Fetching contents of: {target_path}")
    
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Directory not found")
    if not os.path.isdir(target_path):
        raise HTTPException(status_code=400, detail="Path is not a directory")

    return scan_directory(target_path)

@app.get("/read-file")
async def read_file(path: str, currentDir: str | None = None):
    """Read a file's contents."""
    if not base_directory:
        print("No base directory set!")
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        print("\nRead file request:")
        # Normalize base directory path
        normalized_base = os.path.normpath(base_directory).replace('\\', '/')
        print(f"Normalized base directory: {normalized_base}")
        
        # Normalize current directory if provided
        normalized_current = os.path.normpath(currentDir).replace('\\', '/') if currentDir else None
        print(f"Normalized current directory: {normalized_current}")
        
        # Normalize requested path
        normalized_path = path.replace('\\', '/')
        print(f"Normalized requested path: {normalized_path}")

        # Try multiple path resolutions
        paths_to_try = [
            os.path.normpath(os.path.join(normalized_base, normalized_path)),
            os.path.normpath(os.path.join(normalized_current, normalized_path)) if normalized_current else None,
        ]
        paths_to_try = [p for p in paths_to_try if p is not None]

        print(f"Paths to try: {paths_to_try}")

        # Try each path
        for try_path in paths_to_try:
            # Normalize the full path
            full_path = os.path.normpath(try_path).replace('\\', '/')
            print(f"Trying path: {full_path}")
            
            # Security check - make sure the path is within base directory
            if not full_path.startswith(normalized_base):
                print(f"Security check failed for {full_path} (not within {normalized_base})")
                continue
                
            if os.path.exists(full_path) and os.path.isfile(full_path):
                # Read and return the file content with explicit newline handling
                with open(full_path, 'r', encoding='utf-8', newline=None) as f:
                    content = f.read()
                    # Ensure consistent line endings in the response
                    content = content.replace('\r\n', '\n').replace('\r', '\n')
                    
                    # Set response headers to indicate line ending format
                    response = PlainTextResponse(content)
                    response.headers["Content-Type"] = "text/plain; charset=utf-8"
                    response.headers["X-Line-Endings"] = "LF"
                    return response

        # If we get here, no valid path was found
        raise HTTPException(
            status_code=404, 
            detail=f"File not found: {normalized_path}\nTried paths: {paths_to_try}\nBase directory: {normalized_base}"
        )

    except Exception as e:
        print(f"Error reading file {path}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/open-file")
async def open_file():
    """Open a file using dialog and return its contents."""
    dialog = QFileDialog()
    dialog.setFileMode(QFileDialog.ExistingFile)
    
    if dialog.exec_():
        files = dialog.selectedFiles()
        if not files:
            raise HTTPException(status_code=400, detail="No file selected")
        
        file_path = files[0]
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=400, detail="Path is not a file")

        # Check file size
        if os.path.getsize(file_path) > 1024 * 1024:  # 1MB limit
            return PlainTextResponse("[File too large (>1MB)]")

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
                abs_path = os.path.abspath(file_path)
                
                response = PlainTextResponse(content)
                response.headers["Access-Control-Expose-Headers"] = "X-Filename, X-Full-Path"
                response.headers["X-Filename"] = os.path.basename(file_path)
                response.headers["X-Full-Path"] = abs_path
                
                print(f"Opening file: {file_path}")
                print(f"Absolute path: {abs_path}")
                print(f"Response headers: {dict(response.headers)}")
                
                return response
        except Exception as e:
            print(f"Error reading file: {str(e)}")
            return PlainTextResponse(f"[Error reading file: {str(e)}]")
    
    raise HTTPException(status_code=400, detail="No file selected")

@app.post("/read-text", response_class=PlainTextResponse)
async def read_text(request: PathRequest):
    """Read any text file from any path."""
    try:
        file_path = request.path
        print(f"Reading text file: {file_path}")
        
        if not os.path.exists(file_path):
            return f"[Error: File not found: {file_path}]"
        if not os.path.isfile(file_path):
            return f"[Error: Not a file: {file_path}]"

        # Simple size check
        size = os.path.getsize(file_path)
        if size > 1024 * 1024:  # 1MB limit
            return f"[Error: File too large: {size/1024/1024:.1f}MB]"
        if size == 0:
            return ""  # Empty file

        try:
            with open(file_path, 'rb') as f:  # Open in binary mode first
                raw = f.read()
                
                # Try UTF-8 first
                try:
                    return raw.decode('utf-8')
                except UnicodeDecodeError:
                    # If UTF-8 fails, try with errors='replace'
                    return raw.decode('utf-8', errors='replace')
                
        except Exception as e:
            print(f"Error reading file {file_path}: {str(e)}")
            return f"[Error reading file: {str(e)}]"

    except Exception as e:
        print(f"Error in read_text: {str(e)}")
        return f"[Error: {str(e)}]"

@app.post("/rename")
async def rename_item(request: RenameRequest):
    try:
        # Get the absolute path
        abs_path = os.path.join(base_directory, request.path)
        if not os.path.exists(abs_path):
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": f"Path not found: {request.path}"}
            )

        # Get directory and new path
        dir_path = os.path.dirname(abs_path)
        new_abs_path = os.path.join(dir_path, request.new_name)
        
        # Check if target already exists
        if os.path.exists(new_abs_path):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"A file or directory with name '{request.new_name}' already exists"}
            )

        # Perform rename
        os.rename(abs_path, new_abs_path)
        
        # Return new relative path
        new_rel_path = os.path.relpath(new_abs_path, base_directory)
        return {"success": True, "new_path": new_rel_path}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.post("/insert-code")
async def insert_code(request: InsertCodeRequest):
    """Insert or replace code in the currently opened file."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        full_path = os.path.abspath(os.path.join(base_directory, request.path))
        print(f"Inserting code into file: {full_path}")
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=400, detail="Path is not a file")

        # For now, we'll simply replace the entire file content
        # In the future, we could use the position parameter to insert at cursor
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(request.content)

        # Update the cache if the file is cached
        if full_path in file_cache:
            file_cache[full_path] = request.content

        return {'success': True}

    except Exception as e:
        print(f"Error in insert_code: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chats")
async def list_chats():
    chats_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / 'Pointer' / 'chats'
    chats_dir.mkdir(parents=True, exist_ok=True)
    
    chats = []
    for file in chats_dir.glob('*.json'):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                chat = json.load(f)
                # Only include chats that have actual messages (more than just system message)
                if chat.get('messages') and len(chat['messages']) > 1:
                    chats.append(chat)
        except Exception as e:
            print(f"Error reading chat file {file}: {e}")
    
    return sorted(chats, key=lambda x: x.get('createdAt', ''), reverse=True)

@app.get("/chats/{chat_id}")
async def get_chat(chat_id: str):
    """Get a specific chat by ID."""
    try:
        chats_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / 'Pointer' / 'chats'
        chats_dir.mkdir(parents=True, exist_ok=True)
        
        chat_file = chats_dir / f"{chat_id}.json"
        
        if not chat_file.exists():
            return JSONResponse(
                status_code=404,
                content={"detail": "Chat not found"}
            )
            
        with open(chat_file, 'r', encoding='utf-8') as f:
            chat = json.load(f)
            return chat
    except Exception as e:
        print(f"Error reading chat file {chat_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error reading chat: {str(e)}"}
        )

@app.post("/chats/{chat_id}")
async def save_chat(chat_id: str, chat: dict):
    """Save a chat."""
    try:
        chats_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / 'Pointer' / 'chats'
        chats_dir.mkdir(parents=True, exist_ok=True)
        
        chat_file = chats_dir / f"{chat_id}.json"
        with open(chat_file, 'w', encoding='utf-8') as f:
            json.dump(chat, f, indent=2)
        
        return {'success': True}
    except Exception as e:
        print(f"Error saving chat {chat_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error saving chat: {str(e)}"}
        )

@app.get("/completions")
async def get_completions(partial: str = ''):
    if not base_directory:
        return []
    
    # Start with command completions as dictionaries
    completions = [
        {"path": "filestructure", "type": "command"},
        {"path": "files", "type": "command"}
    ]

    # Add file and directory completions
    for root, dirs, files in os.walk(base_directory):
        rel_root = os.path.relpath(root, base_directory)
        if rel_root == '.':
            rel_root = ''
            
        # Add directories
        for dir in dirs:
            path = os.path.join(rel_root, dir)
            if partial.lower() in path.lower():
                completions.append({
                    'path': path,
                    'type': 'directory'
                })
                
        # Add files
        for file in files:
            path = os.path.join(rel_root, file)
            if partial.lower() in path.lower():
                completions.append({
                    'path': path,
                    'type': 'file'
                })
    
    # Sort by type (commands first, then directories, then files) and then by path
    return sorted(completions, key=lambda x: (
        0 if x['type'] == 'command' else 1 if x['type'] == 'directory' else 2,
        x['path']
    ))

@app.get("/files")
async def list_files(currentDir: str | None = None):
    """List all files in the project."""
    try:
        # Use provided currentDir if available, otherwise use base_directory
        working_dir = currentDir if currentDir else base_directory
        
        if not working_dir:
            raise HTTPException(
                status_code=400, 
                detail="No directory opened. Please open a directory first using the file explorer."
            )

        files = []
        for root, _, filenames in os.walk(working_dir):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, working_dir)
                files.append({
                    "path": rel_path.replace("\\", "/"),
                    "type": "file"
                })
        
        if not files:
            return []  # Return empty list if directory is empty
            
        return sorted(files, key=lambda x: x["path"])
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error listing files: {str(e)}"
        )

@app.post("/get-relevant-files")
async def get_relevant_files(request: RelevantFilesRequest):
    """Get files relevant to a search query using keyword extraction."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        # Extract keywords from the query
        keywords = extract_keywords(request.query)
        
        relevant_files = []
        
        # Walk through the directory
        for root, _, files in os.walk(base_directory):
            for file in files:
                if not is_text_file(file):
                    continue
                    
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, base_directory)
                
                try:
                    # Check if file is in cache
                    if file_path in file_cache:
                        content = file_cache[file_path]
                    else:
                        # Read file content if not too large
                        if os.path.getsize(file_path) <= 1024 * 1024:  # 1MB limit
                            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                content = f.read()
                            file_cache[file_path] = content
                        else:
                            continue
                    
                    # Calculate relevance score based on multiple factors
                    score = 0
                    content_lower = content.lower()
                    
                    # 1. Keyword frequency in content
                    for keyword in keywords:
                        keyword_lower = keyword.lower()
                        count = content_lower.count(keyword_lower)
                        if count > 0:
                            # Log scale for frequency to prevent large files from dominating
                            score += (1 + math.log(count)) * 2
                    
                    # 2. Keyword presence in file path (higher weight)
                    path_lower = relative_path.lower()
                    for keyword in keywords:
                        if keyword.lower() in path_lower:
                            score += 5
                    
                    # 3. Keyword proximity (keywords appearing close together)
                    words = content_lower.split()
                    for i in range(len(words)):
                        matches = 0
                        for j in range(5):  # Look at 5-word windows
                            if i + j < len(words) and any(k.lower() in words[i + j] for k in keywords):
                                matches += 1
                        score += matches * 0.5  # Bonus for keywords appearing close together
                    
                    if score > 0:
                        relevant_files.append({
                            'path': relative_path,
                            'score': round(score, 2)  # Round to 2 decimal places
                        })
                except Exception as e:
                    print(f"Error processing file {file_path}: {str(e)}")
                    continue
        
        # Sort by relevance score
        relevant_files.sort(key=lambda x: x['score'], reverse=True)
        
        # Limit the number of results
        relevant_files = relevant_files[:request.max_files]
        
        return {
            'files': relevant_files,
            'keywords': keywords
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/get-file-contents")
async def get_file_contents(files: List[str]):
    """Get the contents of specific files."""
    if not base_directory:
        raise HTTPException(status_code=400, detail="No directory opened")

    try:
        file_contents = {}
        for file_path in files:
            full_path = os.path.join(base_directory, file_path)
            
            try:
                if os.path.exists(full_path) and is_text_file(file_path):
                    if os.path.getsize(full_path) <= 1024 * 1024:  # 1MB limit
                        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read()
                        file_contents[file_path] = content
            except Exception as e:
                print(f"Error reading file {file_path}: {str(e)}")
                continue

        return file_contents
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/terminal")
async def terminal_websocket(websocket: WebSocket):
    await websocket.accept()
    
    # Start PowerShell process
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        process = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoExit", "-NoProfile"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
            bufsize=0,
            universal_newlines=True
        )
    else:
        process = subprocess.Popen(
            ["bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            universal_newlines=True
        )
    
    try:
        async def read_stream(stream):
            while True:
                if stream:
                    try:
                        char = await asyncio.get_event_loop().run_in_executor(
                            None, stream.read, 1
                        )
                        if not char:
                            break
                        await websocket.send_text(char)
                    except Exception as e:
                        print(f"Error reading stream: {e}")
                        break

        # Start reading output and error streams
        output_task = asyncio.create_task(read_stream(process.stdout))
        error_task = asyncio.create_task(read_stream(process.stderr))
        
        while True:
            try:
                data = await websocket.receive_text()
                if process.poll() is not None:
                    break
                if process.stdin:
                    if data == '\x08':  # ASCII backspace character
                        # Send backspace sequence to PowerShell
                        process.stdin.write('\x08 \x08')  # backspace, space, backspace
                        process.stdin.flush()
                    else:
                        process.stdin.write(data)
                        process.stdin.flush()
            except Exception as e:
                print(f"Error in terminal loop: {str(e)}")
                break
                
    except Exception as e:
        print(f"Terminal error: {str(e)}")
    
    finally:
        # Clean up
        try:
            process.terminate()
            await asyncio.sleep(0.1)
            if process.poll() is None:
                process.kill()
        except Exception as e:
            print(f"Error cleaning up process: {e}")
        
        try:
            await websocket.close()
        except Exception as e:
            print(f"Error closing websocket: {e}")

# Remove the uvicorn.run() call since we're using run.py now
if __name__ == "__main__":
    pass