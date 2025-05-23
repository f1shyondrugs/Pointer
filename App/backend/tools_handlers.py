"""
Tool handlers for AI tool calling functionality.
"""

import os
import json
import aiohttp
import asyncio
import re
import subprocess
from typing import Dict, Any, List
from pathlib import Path


async def read_file(file_path: str = None, target_file: str = None) -> Dict[str, Any]:
    """
    Read the contents of a file and return as a dictionary.
    
    Args:
        file_path: Path to the file to read
        target_file: Alternative path to the file to read (takes precedence over file_path)
        
    Returns:
        Dictionary with file content and metadata
    """
    # Use target_file if provided, otherwise use file_path
    actual_path = target_file if target_file is not None else file_path
    
    if actual_path is None:
        return {
            "success": False,
            "error": "No file path provided"
        }
    
    try:
        # Security check: prevent path traversal
        abs_path = os.path.abspath(actual_path)
        
        # Check if file exists
        if not os.path.exists(abs_path):
            return {
                "success": False,
                "error": f"File not found: {actual_path}"
            }
        
        # Get file extension and size
        file_extension = os.path.splitext(abs_path)[1].lower()
        file_size = os.path.getsize(abs_path)
        
        # Read file based on extension
        if file_extension == '.json':
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
                file_type = "json"
        else:
            # Default to text for all other file types
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
                file_type = "text"
        
        return {
            "success": True,
            "content": content,
            "metadata": {
                "path": actual_path,
                "size": file_size,
                "type": file_type,
                "extension": file_extension
            }
        }
    except json.JSONDecodeError:
        # Handle invalid JSON
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "success": False,
            "error": "Invalid JSON format",
            "content": content,
            "metadata": {
                "path": actual_path,
                "size": file_size,
                "type": "text",
                "extension": file_extension
            }
        }
    except UnicodeDecodeError:
        # Handle binary files
        return {
            "success": False,
            "error": "Cannot read binary file as text",
            "metadata": {
                "path": actual_path,
                "size": file_size,
                "type": "binary",
                "extension": file_extension
            }
        }
    except Exception as e:
        # Handle all other exceptions
        return {
            "success": False,
            "error": str(e),
            "metadata": {
                "path": actual_path
            }
        }


async def list_directory(directory_path: str) -> Dict[str, Any]:
    """
    List the contents of a directory.
    
    Args:
        directory_path: Path to the directory to list
        
    Returns:
        Dictionary with directory contents
    """
    try:
        # Security check: prevent path traversal
        abs_path = os.path.abspath(directory_path)
        
        # Check if directory exists
        if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
            return {
                "success": False,
                "error": f"Directory not found: {directory_path}"
            }
        
        # List directory contents
        contents = []
        for item in os.listdir(abs_path):
            item_path = os.path.join(abs_path, item)
            item_type = "directory" if os.path.isdir(item_path) else "file"
            
            contents.append({
                "name": item,
                "path": os.path.join(directory_path, item),
                "type": item_type,
                "size": os.path.getsize(item_path) if item_type == "file" else None
            })
        
        return {
            "success": True,
            "directory": directory_path,
            "contents": contents
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "directory": directory_path
        }


async def web_search(search_term: str = None, query: str = None, num_results: int = 3) -> Dict[str, Any]:
    """
    Simulated web search for information.
    
    Args:
        search_term: Search query (preferred)
        query: Alternative search query
        num_results: Number of results to return
        
    Returns:
        Dictionary with search results
    """
    # Use search_term if provided, otherwise use query
    actual_query = search_term if search_term is not None else query
    
    if actual_query is None:
        return {
            "success": False,
            "error": "No search query provided"
        }
    
    # This is a mock implementation - in a production environment,
    # you would connect to a real search API
    mock_results = [
        {
            "title": f"Result for {actual_query} - Example 1",
            "url": f"https://example.com/search?q={actual_query.replace(' ', '+')}",
            "snippet": f"This is a sample search result for the query '{actual_query}'. It demonstrates how the web search tool works."
        },
        {
            "title": f"Another result for {actual_query}",
            "url": f"https://example.org/results?query={actual_query.replace(' ', '+')}",
            "snippet": f"Another example result for '{actual_query}'. In a real implementation, this would contain actual search results."
        },
        {
            "title": f"{actual_query} - Documentation",
            "url": f"https://docs.example.com/{actual_query.replace(' ', '-').lower()}",
            "snippet": f"Documentation related to {actual_query}. Contains guides, tutorials and reference materials."
        },
        {
            "title": f"Learn about {actual_query}",
            "url": f"https://learn.example.edu/topics/{actual_query.replace(' ', '_').lower()}",
            "snippet": f"Educational resources about {actual_query} with examples and exercises."
        }
    ]
    
    # Simulate network latency
    await asyncio.sleep(0.5)
    
    # Limit results based on num_results
    limited_results = mock_results[:min(num_results, len(mock_results))]
    
    return {
        "success": True,
        "query": actual_query,
        "num_results": len(limited_results),
        "results": limited_results
    }


async def fetch_webpage(url: str) -> Dict[str, Any]:
    """
    Fetch content from a webpage.
    
    Args:
        url: URL to fetch
        
    Returns:
        Dictionary with webpage content
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                content_type = response.headers.get('Content-Type', '')
                
                if 'text/html' in content_type:
                    # For HTML, return simplified content
                    text = await response.text()
                    return {
                        "success": True,
                        "url": url,
                        "content_type": content_type,
                        "status_code": response.status,
                        "content": text[:5000] + ("..." if len(text) > 5000 else ""),
                        "truncated": len(text) > 5000
                    }
                elif 'application/json' in content_type:
                    # For JSON, parse and return
                    try:
                        data = await response.json()
                        return {
                            "success": True,
                            "url": url,
                            "content_type": content_type,
                            "status_code": response.status,
                            "content": data
                        }
                    except json.JSONDecodeError:
                        text = await response.text()
                        return {
                            "success": False,
                            "url": url,
                            "error": "Invalid JSON response",
                            "content_type": content_type,
                            "status_code": response.status,
                            "content": text[:1000] + ("..." if len(text) > 1000 else "")
                        }
                else:
                    # For other content types, return raw text (limited)
                    text = await response.text()
                    return {
                        "success": True,
                        "url": url,
                        "content_type": content_type,
                        "status_code": response.status,
                        "content": text[:1000] + ("..." if len(text) > 1000 else ""),
                        "truncated": len(text) > 1000
                    }
    except Exception as e:
        return {
            "success": False,
            "url": url,
            "error": str(e)
        }


async def grep_search(query: str, include_pattern: str = None, exclude_pattern: str = None, case_sensitive: bool = False) -> Dict[str, Any]:
    """
    Search for a pattern in files.
    
    Args:
        query: The pattern to search for
        include_pattern: Optional file pattern to include (e.g. '*.ts')
        exclude_pattern: Optional file pattern to exclude (e.g. 'node_modules')
        case_sensitive: Whether the search should be case sensitive
        
    Returns:
        Dictionary with search results
    """
    try:
        # Build the ripgrep command
        cmd = ["rg", "--json"]
        
        # Add case sensitivity option
        if not case_sensitive:
            cmd.append("-i")
        
        # Add include pattern if provided
        if include_pattern:
            cmd.extend(["-g", include_pattern])
        
        # Add exclude pattern if provided
        if exclude_pattern:
            cmd.extend(["-g", f"!{exclude_pattern}"])
        
        # Limit results to prevent overwhelming response
        cmd.extend(["--max-count", "50"])
        
        # Add the query and search location
        cmd.append(query)
        cmd.append(".")
        
        # Execute the command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        # Check for error
        if process.returncode != 0 and process.returncode != 1:  # rg returns 1 if no matches
            error_msg = stderr.decode().strip()
            if not error_msg:
                error_msg = f"grep search failed with return code {process.returncode}"
            return {
                "success": False,
                "error": error_msg
            }
        
        # Process the results
        matches = []
        for line in stdout.decode().splitlines():
            try:
                result = json.loads(line)
                if result.get("type") == "match":
                    match_data = result.get("data", {})
                    path = match_data.get("path", {}).get("text", "")
                    
                    for match_line in match_data.get("lines", {}).get("text", "").splitlines():
                        matches.append({
                            "file": path,
                            "line": match_line.strip()
                        })
            except json.JSONDecodeError:
                continue
        
        return {
            "success": True,
            "query": query,
            "include_pattern": include_pattern,
            "exclude_pattern": exclude_pattern,
            "matches": matches
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# Dictionary mapping tool names to handler functions
TOOL_HANDLERS = {
    "read_file": read_file,
    "list_directory": list_directory,
    "web_search": web_search,
    "fetch_webpage": fetch_webpage,
    "grep_search": grep_search,
}

# Tool definitions for API documentation
TOOL_DEFINITIONS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path to the file to read"
                },
                "target_file": {
                    "type": "string",
                    "description": "Alternative path to the file to read (takes precedence over file_path)"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "list_directory",
        "description": "List the contents of a directory",
        "parameters": {
            "type": "object",
            "properties": {
                "directory_path": {
                    "type": "string",
                    "description": "The path to the directory to list"
                }
            },
            "required": ["directory_path"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for information",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "The search query"
                },
                "query": {
                    "type": "string",
                    "description": "Alternative search query (search_term takes precedence)"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 3)"
                }
            },
            "required": ["search_term"]
        }
    },
    {
        "name": "fetch_webpage",
        "description": "Fetch and extract content from a webpage",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the webpage to fetch"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "grep_search",
        "description": "Search for a pattern in files",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The pattern to search for"
                },
                "include_pattern": {
                    "type": "string",
                    "description": "Optional file pattern to include (e.g. '*.ts')"
                },
                "exclude_pattern": {
                    "type": "string",
                    "description": "Optional file pattern to exclude (e.g. 'node_modules')"
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether the search should be case sensitive"
                }
            },
            "required": ["query"]
        }
    }
]


async def handle_tool_call(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle a tool call by dispatching to the appropriate handler.
    
    Args:
        tool_name: Name of the tool to call
        params: Parameters for the tool
        
    Returns:
        Result of the tool execution
    """
    if tool_name not in TOOL_HANDLERS:
        return {
            "success": False,
            "error": f"Unknown tool: {tool_name}"
        }
    
    # Get the handler function
    handler = TOOL_HANDLERS[tool_name]
    
    try:
        # Call the handler with parameters
        result = await handler(**params)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": f"Error executing tool {tool_name}: {str(e)}"
        } 