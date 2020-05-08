import argparse 
import os 
import subprocess 
import sys 
from collections import defaultdict 

parser = argparse.ArgumentParser(description='Running post-processing on media files')
parser.add_argument('indir', help="the location of the media files")
parser.add_argument('outdir', help="the output directory")
parser.add_argument('--concurrency', type=int, default=6, help="the output directory")
parser.add_argument('--dryrun', type=bool, default=False, help="dry run -- just prints the files to be encoded")
args = parser.parse_args()

def scan_directory(directory):
    files = []
    for file in os.listdir(directory):
        if file == "." or file == "..": continue 
        file_path = os.path.join(directory, file)
        if os.path.isfile(file_path):
            yield file_path 
        else:
            yield from scan_directory(file_path)

# find preferred versions of the input files 
input_files = {} # dictionary of input files without extensions
extra_files = defaultdict(list)
video_extensions = ['.mkv', '.mp4', '.flv', '.avi', '.m4v']
extras_extensions = ['.srt']
for file in scan_directory(args.indir):
    file = os.path.relpath(file, args.indir)

    if "Plex Versions" in file:
        continue

    basename, ext = os.path.splitext(file)
    if ext not in video_extensions: continue 

    if (basename not in input_files or (video_extensions.index(os.path.splitext(input_files[basename])[1]) > video_extensions.index(ext))):
        input_files[basename] = file 
        extra_files[basename]
input_files = list(input_files.values()) # list of input files with extensions

print("found %d video files" % len(input_files))

def media_already_exists(file):
    basename, _ = os.path.splitext(file)
    return os.path.exists(os.path.join(args.outdir, basename + ".mkv"))

input_files = list(filter(lambda file: not media_already_exists(file), input_files))
print("files that need encoding: %d" % len(input_files))

input_files.sort(key=lambda file: -os.path.getatime(os.path.join(args.indir, file)))

if args.dryrun:
    print("\n".join(input_files))
    sys.exit(0)

for file in input_files:
    infile = os.path.abspath(os.path.join(args.indir, file))
    outfile = os.path.abspath(os.path.join(args.outdir, file))
    outfile = os.path.splitext(outfile)[0] + ".mkv"

    print(infile + " -> " + outfile)

    p = subprocess.Popen(
        ["python3", "chunk-encode.py", infile, outfile, "--concurrency", str(args.concurrency), "--tmpdir_base", "./tmp"],
        stdin = subprocess.PIPE
    )
    p.wait()
    if p.returncode != 0:
        raise Exception("encountered an error encoding this file")
