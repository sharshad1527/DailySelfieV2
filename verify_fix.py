
import sys
import os

# Ensure core is in path
sys.path.insert(0, os.getcwd())

from core.camera import list_cameras, find_first_camera

def main():
    print("Verifying core.camera fix...")
    try:
        # Check if suppress_stderr is still in globals
        import core.camera
        if hasattr(core.camera, 'suppress_stderr'):
            print("ERROR: suppress_stderr is still defined!")
            sys.exit(1)

        print("suppress_stderr is removed. Running list_cameras...")

        # This should not crash
        cams = list_cameras(4)
        print(f"Cameras found: {len(cams)}")
        for i, res in cams.items():
            print(f"  {i}: available={res.available} read_ok={res.read_ok} msg={res.message}")

        print("Success.")
    except Exception as e:
        print(f"Failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
