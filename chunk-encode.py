import multiprocessing 
import subprocess 
import sys 
import json 
import shlex 
import os 
import shutil
import hashlib 
import argparse 
import math 
import re 
from threading import Lock 
from uuid import uuid4

# input_file = "/mnt/unraid/bigdata-public/media/test/test.mp4"
parser = argparse.ArgumentParser(description='Running post-processing on media files')
parser.add_argument('input_file', help="input file to re-encode")
parser.add_argument('output_file', help="output location for re-encoded file")
parser.add_argument('--concurrency', type=int, default=6, help="number of concurrent transcodes to run")
parser.add_argument('--segment_duration', type=int, default=120, help="chunk duration seconds")
parser.add_argument('--ffmpeg', type=str, default='ffmpeg', help="path to ffmpeg executable")
parser.add_argument('--ffprobe', type=str, default='ffprobe', help="path to ffprobe executable")
parser.add_argument('--tmpdir_base', type=str, default='/tmp/chunk_encode', help="the temporary directory to put encoding artifacts in")
parser.add_argument('--nice', type=int, default=19, help="niceness to use for encoding processes")
args = parser.parse_args()

os.nice(args.nice)

input_file = args.input_file 
output_file = args.output_file 
ffprobe = args.ffprobe 
ffmpeg = args.ffmpeg 

"""
    setup encode working directory
"""
encode_id = os.path.basename(input_file) + "-" + hashlib.sha256(input_file.encode('utf8')).hexdigest()[0:16]
workdir = os.path.join(args.tmpdir_base, encode_id)
if not os.path.exists(workdir):
    os.makedirs(workdir)

print("workdir: " + workdir)

if not os.path.exists(workdir + "/chunks"):
    os.mkdir(workdir + "/chunks")
if not os.path.exists(workdir + "/chunks-encoded"):
    os.mkdir(workdir + "/chunks-encoded")
if not os.path.exists(workdir + "/encode-tmp"):
    os.mkdir(workdir + "/encode-tmp")

# load encode info if available
step_sequence = ["none", "split", "encode", "remux", "validation"]
if os.path.exists(workdir + "/info.json"):
    with open(workdir + "/info.json") as f:
        encode_info = json.load(f)
else:
    encode_info = {
        "last_step_completed": "none"
    }

def write_encode_info(info):
    with open(workdir + "/info.json", "w") as f:
        json.dump(info, f)

print("DETECTED LAST STEP COMPLETED: ", encode_info["last_step_completed"])

"""
    extract media info
"""
p = subprocess.Popen([
    args.ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", input_file
], stdout=subprocess.PIPE, stdin=subprocess.PIPE)
input_file_info = json.loads(p.stdout.read().decode("utf-8"))
p.wait()


"""
    helper functions
"""

def select_stream(media_info, codec_type=None):
    streams = media_info["streams"]
    if type != None:
        streams = filter(lambda stream: stream["codec_type"] == codec_type, streams)
    return list(streams)


"""
    extract video stream information
"""
video_stream = select_stream(input_file_info, codec_type="video")[0]
print(json.dumps(input_file_info, indent=2))

fps = eval(video_stream["avg_frame_rate"]) # 1000000% unsafe lol, todo: fix this
video_resolution = video_stream["width"] * video_stream["height"]
video_duration = float(input_file_info["format"]["duration"])
expected_chunk_count = math.ceil(video_duration / args.segment_duration)

"""
    STEP 1: split video stream into segments
"""
def check_file_count(dir, filter):
    return sum(1 if filter(file) else 0 for file in os.listdir(dir))

if step_sequence.index(encode_info["last_step_completed"]) < step_sequence.index("split"):
    # chunk size is 30 seconds here
    command_ffmpeg = """
        {ffmpeg} -i {input_file} -c copy -map 0:v -segment_time {segment_duration} -f segment {chunk_pattern}
    """.format(
        ffmpeg = ffmpeg, 
        input_file = shlex.quote(input_file),
        segment_duration = args.segment_duration,
        workdir = workdir,
        chunk_pattern = shlex.quote(workdir + "/chunks/output%03d.mkv")
    )
    p_ffmpeg = subprocess.Popen(shlex.split(command_ffmpeg), stdin=subprocess.PIPE)
    p_ffmpeg.wait()

    encode_info["last_step_completed"] = "split"
    assert(check_file_count(workdir + "/chunks/", lambda file: file.endswith(".mkv")) == expected_chunk_count)
    write_encode_info(encode_info)
else: 
    assert(check_file_count(workdir + "/chunks/", lambda file: file.endswith(".mkv")) == expected_chunk_count)

"""
    STEP 2: transcode the segments into the desired format 
"""
from multiprocessing.pool import ThreadPool

if step_sequence.index(encode_info["last_step_completed"]) < step_sequence.index("encode"):
    encode_lock = Lock()

    def encode(input):
        srcfile, dstfile = input 

        if srcfile in encode_info["encode_chunks_completed"]:
            print("skipping encoding file -- already in completed chunks list")
            return 

        tmpdir = workdir + "/encode-tmp/" + str(uuid4())
        
        os.makedirs(tmpdir)
        print("\tworking in tempdir: " + tmpdir)
        try:
            pass1_command = """
            {ffmpeg} -i {input_file} -map 0:v:0 -c:v libvpx-vp9 -pass 1 
                COMMON_VIDEO_OPTIONS 
                -cpu-used 8 -threads 16 -speed 4 -max_muxing_queue_size 1024 
                -tile-columns 3 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 16 
                -f matroska /dev/null -y 
            """.format(
                ffmpeg = ffmpeg,
                input_file = shlex.quote(srcfile)
            )

            pass2_command = """
            {ffmpeg} -i {input_file} -map 0:v:0 -c:v libvpx-vp9 -pass 2 
                COMMON_VIDEO_OPTIONS
                -cpu-used 8 -threads 16 -speed {speed} -max_muxing_queue_size 1024 
                -tile-columns 3 -frame-parallel 1 -auto-alt-ref 1 -lag-in-frames 16 
                -f matroska {output_file} -y 
            """.replace("\n", "").format(
                ffmpeg = ffmpeg,
                input_file = shlex.quote(srcfile), 
                output_file = shlex.quote(dstfile),
                speed = 2 if video_resolution < 1920 * 1080 * 1.5 else 3,
            )

            common_video_options = """
            -b:v 0k -crf {crf}
            -pix_fmt yuv420p10le -color_range 1 
            -profile:v 2
            -g 240 
            """.format(crf = 26)

            pass1_command = pass1_command.replace("COMMON_VIDEO_OPTIONS", common_video_options)
            pass2_command = pass2_command.replace("COMMON_VIDEO_OPTIONS", common_video_options)

            print(pass1_command)
            p = subprocess.Popen(shlex.split(pass1_command), stdin=subprocess.PIPE, cwd=tmpdir)
            p.wait()

            print(pass1_command)
            p = subprocess.Popen(shlex.split(pass2_command), stdin=subprocess.PIPE, cwd=tmpdir)
            p.wait()

            with encode_lock:
                encode_info["encode_chunks_completed"].append(srcfile)
                write_encode_info(encode_info)

        finally:
            if tmpdir:
                shutil.rmtree(tmpdir)

        # srcfile, dstfile = input 
        # command_ffmpeg = """
        #     ffmpeg -i {srcfile} {dstfile}
        # """.format(srcfile = shlex.quote(srcfile), dstfile = shlex.quote(dstfile))
        # p_ffmpeg_worker = subprocess.Popen(shlex.split(command_ffmpeg), stdin=subprocess.PIPE)
        # p_ffmpeg_worker.wait()

    if "encode_chunks_completed" not in encode_info:
        encode_info["encode_chunks_completed"] = []
        write_encode_info(encode_info)
    
    with ThreadPool(args.concurrency) as pool:
        inputs = [(os.path.abspath(workdir + "/chunks/" + file), os.path.abspath(workdir + "/chunks-encoded/" + file)) for file in os.listdir(workdir + "/chunks") if file.endswith(".mkv")]
        pool.map(encode, inputs, 1)

    # TODO: use the encode info to setup resumable encode by saving the queue :P 
    encode_info["last_step_completed"] = "encode"
    assert(check_file_count(workdir + "/chunks-encoded/", lambda file: file.endswith(".mkv")) == expected_chunk_count)
    write_encode_info(encode_info)

"""
    STEP 3: join the segments together
"""
if step_sequence.index(encode_info["last_step_completed"]) < step_sequence.index("remux"):
    with open(workdir + "/chunks-encoded/concat.txt", "w") as f:
        f.write("\n".join([
            "file '%s'" % file 
            for file in sorted(os.listdir(workdir + "/chunks-encoded"))
            if file.endswith(".mkv")
        ]))

    # we analyze and map subtitle streams manually
    substream_mappings = []
    for idx, substream in enumerate(select_stream(input_file_info, codec_type="subtitle")):
        if substream["codec_name"] == "mov_text":
            substream_mappings.append("-map 1:s:" + str(idx) + " -c:s srt")
        else:
            substream_mappings.append("-map 1:s:" + str(idx) + " -c:s copy")
    substream_mappings = " ".join(substream_mappings)

    command_ffmpeg = """
        {ffmpeg} -r {fps} -f concat -safe 0 -i {concat_file} -i {input_file} -map_metadata 1 -map 0:v -c:v copy 
        -map 1:a -map 1:a -c:a libopus -b:a 160k -vbr on -ac 2 
        {substream_mappings} -f matroska {output_file} -y
    """.format(
        ffmpeg = ffmpeg, 
        input_file = shlex.quote(input_file), 
        concat_file = shlex.quote(workdir + "/chunks-encoded/concat.txt"),
        output_file = shlex.quote(workdir + "/output.mkv"), 
        fps = fps, 
        substream_mappings = substream_mappings,
    )
    print(command_ffmpeg)
    p_ffmpeg = subprocess.Popen(shlex.split(command_ffmpeg), stdin=subprocess.PIPE)
    p_ffmpeg.wait()
    if p_ffmpeg.returncode != 0:
        raise Exception("ffmpeg exited with non-zero return code")

    encode_info["last_step_completed"] = "remux"
    write_encode_info(encode_info)

#
# VALIDATION 
#
if step_sequence.index(encode_info["last_step_completed"]) < step_sequence.index("validation"):
    def check_framecount(videofile):
        p = subprocess.Popen(
            ["ffmpeg", "-i", videofile, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"], 
            stdin=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        lines = p.stderr.read().decode("utf-8").split("\n")
        print(lines)
        frameline = None 
        for line in lines:
            line = line.split("\r")
            for seg in line:
                if seg.startswith("frame"):
                    frameline = seg 
        p.wait()
        segments = re.sub(' +', ' ', frameline.replace("=", " ")).split(" ")
        return int(segments[1])

    print("finally, validating that input and output frame counts match.")
    input_frame_count = check_framecount(input_file)
    output_frame_count = check_framecount(workdir + "/output.mkv")
    print("input frames: " + str(input_frame_count) + " == output frames: " + str(output_frame_count))
    assert(input_frame_count == output_frame_count)

    if not os.access(os.path.dirname(output_file), os.F_OK):
        os.makedirs(os.path.dirname(output_file))
    shutil.move(workdir + "/output.mkv", args.output_file)

    encode_info["last_step_completed"] = "validation"
    write_encode_info(encode_info)

# shutil.rmtree(workdir)
