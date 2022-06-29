#   URL File Downloader...
#
# Run with
#   python -m jcr.urldownloader --input images.txt --root-url https://alexiy.nl/eq_chart/

def download_urls_from_file(input_file, output_dir=None, root_url=None):
    """
    Download a list of URLs from a file of newline separated URLs.
    """
    urls = list()
    with open(input_file) as fp:
        for idx, line in enumerate(fp):
            urls.append(line.strip())
        download_urls(urls, output_dir=output_dir, root_url=root_url)

def download_urls(urls, output_dir="python_url_downloads", root_url=None):
    """
    Download a list of URLs.
    """
    for idx, line in enumerate(urls):
        m = re.search('^([a-zA-Z]+://)',line)
        if m:
            # The url already has a protocol
            # line[m.span(0)[1]:] # Get the url without protocol line
            url = line
            filename = os.path.basename(line)
        else:
            # No match, the url is without a protocol
            assert root_url is not None, f"ROOT_URL is not set when attempting to fetch url for '{line}'"
            url = os.path.join(ROOT_URL, line)
            filename = line

        response = requests.get(url)
        outputfile = os.path.join(output_dir, filename)
        os.makedirs(os.path.dirname(outputfile), exist_ok=True)
        with open(outputfile, "wb") as outfile:
            print(f"Writing: {outputfile}")
            outfile.write(response.content)


if __name__ == "__main__":

    import argparse
    from argparse import RawTextHelpFormatter
    from pathlib import Path
    import re
    import os
    import requests

    parser = argparse.ArgumentParser(
        description="""Python URL File Downloader\n\n""",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Path to URLs file, each line is a URL of a file to download.",
        required=True
    )

    parser.add_argument("--root-url", type=str, default=None, help="Root URL in the case that files are provided as relative URLs")

    parser.add_argument(
        "--output", "-o",
        type=str,
        default="pythondownload",
        help="Destination download folder.",
    )

    args = parser.parse_args()

    INPUT_FILE = Path(args.input)
    ROOT_URL = args.root_url
    OUTPUT_DIR = args.output

    download_urls_from_file(INPUT_FILE, root_url=ROOT_URL, output_dir=OUTPUT_DIR)
