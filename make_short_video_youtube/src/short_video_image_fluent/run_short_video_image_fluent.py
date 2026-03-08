import os
import subprocess
import sys
from pathlib import Path

def run_step(script_path: Path):
    print(f"\n{'='*80}")
    print(f"🚀 Running: {script_path.name}")
    print(f"{'='*80}\n")
    
    # Run the script using the current python executable
    result = subprocess.run([sys.executable, str(script_path)], cwd=str(script_path.parent.parent.parent))
    
    if result.returncode != 0:
        print(f"\n❌ Pipeline stopped: {script_path.name} failed with exit code {result.returncode}.")
        sys.exit(result.returncode)

def main():
    root_dir = Path(__file__).resolve().parent
    
    step1 = root_dir / "step1_generate_content.py"
    step2 = root_dir / "step2_generate_audio.py"
    step3 = root_dir / "step3_generate_video.py"
    step4 = root_dir / "step4_generate_metadata.py"
    
    if not step1.exists() or not step2.exists() or not step3.exists() or not step4.exists():
        print("❌ Could not find all the pipeline scripts in the current directory.")
        sys.exit(1)
        
    print("🎬 SocialHarvester Complete Video Pipeline 🎬")
    
    run_step(step1)
    run_step(step2)
    run_step(step3)
    run_step(step4)
    
    print(f"\n{'='*80}")
    print("🎉 Pipeline Completed Successfully! 🎉")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
