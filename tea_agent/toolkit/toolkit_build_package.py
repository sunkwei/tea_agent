## llm generated tool func, created Thu Apr 16 16:20:47 2026

def toolkit_build_package():
    """
    Builds the Python project in the current directory.
    Handles the common issue where a local 'build' folder shadows the 'build' package.
    """
    import os
    import sys
    import subprocess
    import datetime

    cwd = os.getcwd()

    # 1. Check for local 'build' directory shadowing
    local_build_dir = os.path.join(cwd, "build")
    renamed_dir = None
    
    if os.path.isdir(local_build_dir):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        renamed_dir = os.path.join(cwd, f"build_shadow_{ts}")
        print(f"⚠️ Detected local 'build' directory. Renaming to '{os.path.basename(renamed_dir)}' to avoid shadowing...")
        os.rename(local_build_dir, renamed_dir)

    try:
        # 2. Ensure pyproject.toml exists
        if not os.path.exists(os.path.join(cwd, "pyproject.toml")):
            print("❌ Error: pyproject.toml not found in current directory.")
            return 1

        # 3. Ensure 'build' package is installed
        print("📦 Ensuring 'build' package is installed...")
        install_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "build", "--quiet"],
            capture_output=True,
            text=True
        )
        if install_result.returncode != 0:
            print(f"⚠️ Failed to install 'build' package: {install_result.stderr}")
        
        # 4. Run the build
        print("🔨 Running 'python -m build'...")
        result = subprocess.run(
            [sys.executable, "-m", "build"],
            cwd=cwd,
            capture_output=True,
            text=True
        )
        
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)

        if result.returncode == 0:
            print("✅ Build successful!")
        else:
            print(f"❌ Build failed with exit code {result.returncode}")
            return result.returncode
            
    finally:
        # 5. Restore the directory if it was renamed
        if renamed_dir and os.path.exists(renamed_dir):
            if os.path.exists(local_build_dir):
                print(f"⚠️ The build process created a 'build' directory. Keeping your original directory as '{os.path.basename(renamed_dir)}' to prevent overwriting.")
            else:
                os.rename(renamed_dir, local_build_dir)
                print("♻️ Restored 'build' directory.")

    return 0

def meta_toolkit_build_package() -> dict:
    return {"type": "function", "function": {"name": "toolkit_build_package", "description": "Builds the Python project in the current directory, automatically handling the common issue where a local 'build' folder shadows the 'build' package.", "parameters": {"type": "object", "properties": {}}}}
