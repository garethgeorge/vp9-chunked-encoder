# VP9 Chunked Encoder

Google's libvpx vp9 encoder is poorly optimized for multithreaded use which results in poor CPU utiliation and thus low encode speeds. 
This situation is dramatically improved by first segmenting files to be encoded and then processing those segments. Finally, these segments 
can be recombined as a single vp9 encoded video stream in a mkv container.

## Dependencies 

This project depends on having a build of ffmpeg capable of 10bit encodes, alternatively you can edit the ffmpeg settings used in chunk-encode.py to output 8bit video.
10-bit video is used by default as it reduces color accuracy loss as a result of quantizer errors in the vp9 encoder. This can badly artifact dark scenes in VP9 in my oppinion, but your milage may vary.

To install a 10bit version of vp9 there are two good options.

 1. google provides a build script to build your own: https://github.com/id3as/ffmpeg-libvpx-HDR-static 
 2. use a docker container: ``docker pull lastpenguin/ffmpeg-vp9-10bit`` and ``docker run -v $(pwd):/data -v --name transcode -it lastpenguin/ffmpeg-vp9-10bit bash``

## chunk-encode usage 

to run chunk-encode you are expected to provide an input and output video file for encoding as follows:
```
python3 chunk-encode.py <input file> <output file> --tmpdir <temp directory to use> --concurrency <number of ffmpeg workers>
```

use -h to get usage information for chunk-encode.py 
```plain
bash$ python3 chunk-encode.py -h
usage: chunk-encode.py [-h] [--concurrency CONCURRENCY] [--segment_duration SEGMENT_DURATION] [--ffmpeg FFMPEG] [--ffprobe FFPROBE] [--tmpdir_base TMPDIR_BASE] [--nice NICE] input_file output_file

Running post-processing on media files

positional arguments:
  input_file            input file to re-encode
  output_file           output location for re-encoded file

optional arguments:
  -h, --help            show this help message and exit
  --concurrency CONCURRENCY
                        number of concurrent transcodes to run
  --segment_duration SEGMENT_DURATION
                        chunk duration seconds
  --ffmpeg FFMPEG       path to ffmpeg executable
  --ffprobe FFPROBE     path to ffprobe executable
  --tmpdir_base TMPDIR_BASE
                        the temporary directory to put encoding artifacts in
  --nice NICE           niceness to use for encoding processes
```

## encode-files usage 

Encode files is a provided helper for batch encoding large media collections. Again, usage is designed to be straight forward. It will take all unencoded files from some input directory, and check for copies in an output directory. If none are found, it will encode then as mkv files using VP9 video.

```
python3 encode-files.py <input directory> <output directory> --concurrency <number of workers>
```

use -h to get the help info for encode-files 

```
usage: encode-files.py [-h] [--concurrency CONCURRENCY] [--dryrun DRYRUN] indir outdir

Running post-processing on media files

positional arguments:
  indir                 the location of the media files
  outdir                the output directory

optional arguments:
  -h, --help            show this help message and exit
  --concurrency CONCURRENCY
                        the output directory
  --dryrun DRYRUN       dry run -- just prints the files to be encoded
```
