import subprocess
import sys
import os
import time

def run():
    # Root path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Start backend process
    # Use the same python executable to run uvicorn
    backend_cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    print("Starting backend server...")
    backend_process = subprocess.Popen(
        backend_cmd,
        cwd=root_dir
    )
    
    # 2. Start frontend process
    # On Windows, we need shell=True to run npm command
    frontend_dir = os.path.join(root_dir, "frontend")
    print("Starting frontend server...")
    frontend_process = subprocess.Popen(
        "npm run dev",
        shell=True,
        cwd=frontend_dir
    )
    
    print("\nBoth backend and frontend are starting up!")
    print("Press Ctrl+C to stop both servers.\n")
    
    try:
        # Keep the script running to monitor processes
        while True:
            # Check if any process terminated unexpectedly
            backend_rc = backend_process.poll()
            frontend_rc = frontend_process.poll()
            
            if backend_rc is not None:
                print(f"Backend stopped with code {backend_rc}")
                break
            if frontend_rc is not None:
                print(f"Frontend stopped with code {frontend_rc}")
                break
                
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        # Terminate processes cleanly
        if backend_process.poll() is None:
            backend_process.terminate()
            
        if frontend_process.poll() is None:
            if os.name == 'nt':
                # On Windows, kill the entire process tree to avoid orphaned node processes
                subprocess.run(
                    f"taskkill /F /T /PID {frontend_process.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                frontend_process.terminate()
        
        # Wait for processes to exit
        backend_process.wait()
        frontend_process.wait()
        print("Servers stopped.")

if __name__ == "__main__":
    run()
