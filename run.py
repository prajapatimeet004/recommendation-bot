import subprocess
import sys
import os
import time
import shutil

def setup_and_run():
    # Root path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("=" * 60)
    print("      AI Shopping Assistant Setup & Launcher      ")
    print("=" * 60)

    # 1. Check and copy env file
    env_path = os.path.join(root_dir, "backend", ".env")
    env_example = os.path.join(root_dir, "backend", ".env.example")
    if not os.path.exists(env_path) and os.path.exists(env_example):
        print("[*] Creating backend/.env from .env.example...")
        shutil.copyfile(env_example, env_path)
        print("[+] Created backend/.env successfully.")

    # 2. Check and configure python virtual environment
    venv_dir = os.path.join(root_dir, ".venv")
    if os.name == 'nt':
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
        venv_pip = os.path.join(venv_dir, "Scripts", "pip.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")
        venv_pip = os.path.join(venv_dir, "bin", "pip")

    if not os.path.exists(venv_python):
        print("[*] Virtual environment (.venv) not found. Creating it...")
        try:
            subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=root_dir, check=True)
            print("[+] Virtual environment created successfully.")
        except Exception as e:
            print(f"[-] Failed to create virtual environment: {e}")
            print("Please ensure you have Python venv module installed.")
            sys.exit(1)

    # 3. Switch context to the virtual environment python if not running within it
    if sys.executable != venv_python:
        print("[*] Switching launcher context to .venv python...")
        cmd = [venv_python, __file__] + sys.argv[1:]
        try:
            sys.exit(subprocess.call(cmd))
        except Exception as e:
            print(f"[-] Failed to launch under .venv: {e}")
            sys.exit(1)

    # We are now guaranteed to be running inside the virtual environment context
    # 4. Check and install Python dependencies
    try:
        import fastapi
        import uvicorn
        import dotenv
        import httpx
        import litellm
        import chromadb
        import tavily
        print("[+] All Python dependencies are already installed.")
    except ImportError:
        print("[*] Some Python dependencies are missing. Installing backend/requirements.txt...")
        requirements_path = os.path.join(root_dir, "backend", "requirements.txt")
        try:
            subprocess.run([venv_pip, "install", "-r", requirements_path], cwd=root_dir, check=True)
            print("[+] Python dependencies installed successfully.")
        except Exception as e:
            print(f"[-] Failed to install requirements: {e}")
            sys.exit(1)

    # 5. Check and install Node dependencies
    frontend_dir = os.path.join(root_dir, "frontend")
    node_modules_dir = os.path.join(frontend_dir, "node_modules")
    if not os.path.exists(node_modules_dir):
        print("[*] node_modules not found in frontend. Running npm install...")
        try:
            subprocess.run("npm install", shell=True, cwd=frontend_dir, check=True)
            print("[+] Node dependencies installed successfully.")
        except Exception as e:
            print(f"[-] Failed to run npm install: {e}")
            print("Please make sure Node.js and npm are installed and in your system PATH.")
            sys.exit(1)
    else:
        print("[+] Frontend dependencies (node_modules) are already installed.")

    # 6. Start processes
    print("\n" + "=" * 60)
    print("      Starting Backend & Frontend Servers      ")
    print("=" * 60)

    # Start backend process using .venv python
    backend_cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    print("[*] Launching backend on http://localhost:8000 ...")
    backend_process = subprocess.Popen(
        backend_cmd,
        cwd=root_dir
    )
    
    # Start frontend process
    print("[*] Launching frontend on http://localhost:5173 ...")
    frontend_process = subprocess.Popen(
        "npm run dev",
        shell=True,
        cwd=frontend_dir
    )
    
    print("\n[+] Both backend and frontend are running!")
    print("👉 Frontend: http://localhost:5173")
    print("👉 Backend: http://localhost:8000")
    print("👉 API Documentation: http://localhost:8000/docs")
    print("👉 Press Ctrl+C to stop both servers safely.\n")
    
    try:
        while True:
            # Check if any process terminated unexpectedly
            backend_rc = backend_process.poll()
            frontend_rc = frontend_process.poll()
            
            if backend_rc is not None:
                print(f"\n[-] Backend stopped with exit code {backend_rc}")
                break
            if frontend_rc is not None:
                print(f"\n[-] Frontend stopped with exit code {frontend_rc}")
                break
                
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n[!] Ctrl+C detected. Stopping servers...")
    finally:
        # Cleanly stop backend
        if backend_process.poll() is None:
            if os.name == 'nt':
                subprocess.run(
                    f"taskkill /F /T /PID {backend_process.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                backend_process.terminate()
            
        # Cleanly stop frontend
        if frontend_process.poll() is None:
            if os.name == 'nt':
                # On Windows, kill process tree to clean up node/vite subprocesses
                subprocess.run(
                    f"taskkill /F /T /PID {frontend_process.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                frontend_process.terminate()
        
        backend_process.wait()
        frontend_process.wait()
        print("[+] Both servers stopped successfully.")

if __name__ == "__main__":
    setup_and_run()
