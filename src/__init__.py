import os
import sys
import json
import shutil
import traceback
import argparse
import requests
import lxml.html as html
from progress.bar import Bar

PINTEREST_HOST = "https://pinterest.com"
Response = requests.models.Response


def user_profile_board_resource(data_items: list) -> list:
    """
    Accepts board resource (UserProfileBoardResource) and returns restructured dict for easy manipulation

    Parameters
    ---------
    data_items: list
       UserProfileBoardResource - list of user boards

    Returns
    ------
    [
          {
            "id": number,   # Board id
            "url": str,     # Board url e.g. username/board_name
            "owner": str,   # username
            "name": str     # board_name
          },
    ]

    """
    if not isinstance(data_items, list):
        raise ValueError("Wrong object provided")

    result = []

    for i in data_items:
        result.append({
            "id": i["id"],
            "url": i["url"],
            "owner": i["owner"]["username"],
            "name": i["name"],
        })

    return result


def get_page_data(path: str) -> dict:
    """
    Request path and return structured data

    Parameters
    ----------
    path: str
        Pinterest path e.g. username or username/board_name


    Returns
    -------
    dict
        {
            "UserProfileBaseResource": {
                {
                "status": str "<success|failure>",
                "status_code: number <200|404|...>,
                "data": {<user_json_data>}|None,
                "error": "Occurred error",
              }
            },
            "UserProfileBoardResource": {
                "status": str "<success|failure>",
                "status_code: number <200|404|...>,
                "data": [<board_json_data>]| [] | None,
                "error": "Occurred error",
            },
        }
    """
    s = session()
    r = s.get("{}/{}/".format(PINTEREST_HOST, path))
    root = html.fromstring(r.content)
    tag = root.xpath("//script[@id='initial-state']")[0]
    responses = json.loads(tag.text)["resourceResponses"]

    result = {}

    for item in responses:

        result[item["name"]] = {
            "status": item["response"]["status"],
            "status_code": item["response"]["http_status"],
            "data": item["response"]["data"],
        }

        if response_has_errors(item):
            result["error"] = response_error_message(item)

    return result


def user_boards(username: str) -> dict:
    """
    Gets list of boards

    Parameters
    ---------
    username: str
          Pintereset Username

    Returns
    -------
    list of boards
        [
          {
            "id": number,   # Board id
            "url": str,     # Board url e.g. username/board_name
            "owner": str,   # username
            "name": str     # board_name
          },
          {
            ...
          }
        ]
    Raises
    ------
    UserBoardException

    """
    data: dict = get_page_data(username)

    if "error" in data:
        raise UserBoardException(data["error"])

    result: dict = data["UserProfileBoardResource"]
    result["data"]: list = user_profile_board_resource(result["data"])

    if len(result["data"]) > 0:
        return result["data"]

    raise UserBoardException("User does not have any boards")


def get_links(board: dict) -> list:
    """
    Retrieve downloadable links from a board

    Parameters
    ---------
    board: dict
        Pinterest board
            {
                "id": number,   # Board id
                "url": str,     # Board url e.g. username/board_name
                "owner": str,   # username
                "name": str     # board_name
            }


    Returns
    -------
    list
        [
            {
                "type": str,    # image | video
                "id": str,      # numeric id
                "url": str,     # url to image or video stream
            }
        ]

    """
    s = session()
    bookmark = None
    resources = []

    while bookmark != '-end-':
        options = {
            "board_id": board["id"],
            "page_size": 25,
        }

        if bookmark:
            options.update({
                "bookmarks": [bookmark],
            })

        r = s.get("{}/resource/BoardFeedResource/get/".format(PINTEREST_HOST), params={
            "source_url": board["url"],
            "data": json.dumps({
                "options": options,
                "context": {},
            }),
        })

        data = r.json()
        resources += data["resource_response"]["data"]
        bookmark = data["resource"]["options"]["bookmarks"][0]

    originals = []
    for res in resources:
        # Get original image url
        if ("images" in res) and (res["videos"] is None):
            originals.append({
                "type": "image",
                "id": res["id"],
                "url": res["images"]["orig"]["url"],
            })

        # Get video download url
        if "videos" in res and (res["videos"] is not None):
            originals.append({
                "type": "video",
                "id": res["id"],
                "url": res["videos"]["video_list"]["V_HLSV4"]["url"],
            })

    return originals


def fetch_image(url: str, save_path: str) -> None:
    """
    Download image resource

    Parameters
    ----------

    url: str
        File URL
    save_path:
        Save location

    """
    try:
        r = requests.get(url, stream=True)
        with open(save_path, "wb") as f:
            for chunk in r:
                f.write(chunk)
    except Exception as e:
        log(e, "[Download Image Exception]")


def get_stream_urls(url: str) -> dict:
    """
    Picks a stream with best resolution from provided url
    Requests that playlist and returns list of streams
    """
    r: Response = requests.get(url, stream=True)
    best_quality: str

    line: bytes
    for line in r.iter_lines():
        decoded_url: str = line.decode("utf-8")
        if (not decoded_url) or (not decoded_url.endswith("m3u8")): continue
        best_quality = decoded_url

    splitted_url: list = url.split("/")
    splitted_url[-1]: str = best_quality
    url: str = "/".join(splitted_url)

    streams: Response = requests.get(url, stream=True)
    stream_urls: list = []

    for line in streams.iter_lines():
        decoded_url: str = line.decode("utf-8")
        if (not decoded_url) or (not decoded_url.endswith("ts")): continue
        stream_url: list = url.split("/")
        stream_url[-1] = decoded_url
        stream_urls.append("/".join(stream_url))

    return stream_urls


def fetch_video(playlist_url: str, save_path: str):
    """
    Downloads video resource
    Downloads playlist containing resources available for stream, downloads and combines streams together

    Parameters
    ---------
    playlist_url: str
        Video resource available for stream (.m3u8 file format)

    save_path: str
        Where video resource should be saved

    """
    try:
        streams: list = get_stream_urls(playlist_url)
        url: str
        for url in streams:
            ts_stream: Response = requests.get(url, stream=True)
            with open(save_path, "ab") as merged:
                shutil.copyfileobj(ts_stream.raw, merged)
    except Exception as e:
        log(e, "[Download Video Exception]")


def fetch_boards(links: dict, save_folder: str, force: bool=False) -> None:
    """
    Downloads Pinterest board resources

    Parameters
    ----------
    links: dict
        Pinterest board

    save_folder: str
        Folder where to save

    force: bool
        Forces re-download of resource
    """
    if not links:
        raise ValueError("Links parameter cannot be empty")

    if not save_folder:
        raise ValueError("Folder parameter is empty")

    if not isinstance(links, list):
        raise TypeError("Links has wrong type")

    for el in Bar("Downloading").iter(links):
        ext = el["url"].split(".")[-1]
        filename = "{}.{}".format(el["id"], ext)
        save_path = os.path.join(save_folder, filename)
        exists = os.path.exists(save_path)

        if not exists or force:
            # Download images
            if el["type"] == "image":
                make_dir(save_folder)
                fetch_image(el["url"], save_path)
            # Download video
            if el["type"] == "video":
                save_path = os.path.join(save_folder, "{}.{}".format(el["id"], "ts"))
                make_dir(save_folder)
                fetch_video(el["url"], save_path)


def session():
    """
    Returns request session with pre-defined headers
    """
    s = requests.Session()
    s.headers = {
        "Referer": PINTEREST_HOST,
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36",
    }

    return s


def response_has_errors(response_item):
    """
    Checks if response contains errors
    """
    if "response" not in "response_item":
        raise ValueError("Response item was not found")

    if "error" in response_item["response"]:
        return True


def response_error_message(response_item):
    """
    Returns response error message
    """
    if not response_has_errors(response_item):
        raise ValueError("Response item does not have errors")

    error_object = response_item["response"]["error"]["message"].split(" - ")[1]
    json_error = json.loads(error_object)

    return json_error["message"]


def make_dir(dir: str) -> None:
    """
    Creates directory if not exists
    """
    try:
        os.makedirs(dir)
    except Exception:
        pass


def log(e: Exception, header: str = "", trace: bool = False) -> None:
    """
    Logs exceptions to stdout
    """
    if not header == "":
        print("{} {}".format(header, str(e)))
    else:
        print("{}".format(str(e)))

    if traceback:
        print("Traceback:")
        print("".join(traceback.format_tb(e.__traceback__)))


class UserBoardException(Exception):
    pass


def main():
    args_parser = argparse.ArgumentParser(description="Download Pinterest boards")
    args_parser.add_argument("-f", "--force", type=bool, default=False,
                             help="Forces redownlaod, overwrite existing files")
    args_parser.add_argument("-s", "--save-folder", type=str, default="download", help="Sets save location")
    args_parser.add_argument("path", type=str, help="Pinterest username or username")

    args = args_parser.parse_args()

    args.path = args.path.strip("/")
    print("Downloading from {}".format(args.path))
    try:
        boards = user_boards(args.path)

        for board in boards:
            links = get_links(board)
            save_folder = os.path.join(args.save_folder, board["owner"], board["name"])
            fetch_boards(links, save_folder, args.force)

    except Exception as e:
        log(e=e, trace=True)

if __name__ == "__main__":
    main()
