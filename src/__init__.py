import os
import json
import shutil
import traceback
import argparse
import requests
import lxml.html as html
from enum import Enum
from progress.bar import Bar
from typing import List, Union, Any, NewType

PINTEREST_HOST = "https://pinterest.com"
Response = requests.models.Response
Session = requests.Session


class UserBoardException(Exception):
    pass


class Board:
    id: str  # Board id
    url: str  # Board url e.g. username/board_name
    owner: str  # username
    name: str  # board_name

    def __init__(self, board_id: str = None, url: str = None, owner: str = None, name: str = None):
        self.id = board_id
        self.url = url
        self.owner = owner
        self.name = name


class DownloadableResourceType(Enum):
    image = 'image'
    video = 'video'


class DownloadableResource:
    type: NewType('DownloadableResourceType', DownloadableResourceType)
    id: str
    url: str  # url to image or video stream


class UserProfileBaseResource:
    status: str
    status_code: int
    data: Union[List[Any], None]


class UserProfileBoardResource(UserProfileBaseResource):
    pass


class UserProfileResources:
    UserProfileBaseResource: 'UserProfileBaseResource' = UserProfileBaseResource()
    UserProfileBoardResource: 'UserProfileBoardResource' = UserProfileBoardResource()
    error: str = None


def user_profile_board_resource(data_items: List[Any]) -> List[Board]:
    """
    Accepts board resource (UserProfileBoardResource) and returns restructured list of Boards for easy manipulation
    :param data_items:  List of user boards
    :return: List of user Boards
    """
    if not isinstance(data_items, list):
        raise ValueError("Wrong object provided")

    result = []

    for i in data_items:
        board = Board()
        board.id = i["id"]
        board.url = i["url"]
        board.owner = i["owner"]["username"]
        board.name = i["name"]

        result.append(board)

    return result


def get_page_data(path: str) -> 'UserProfileResources':
    """
     Requests pinterest page and returns structured data

    :param path: Pinterest path e.g. username or username/board_name
    :return:
    """
    s = session()
    r = s.get("{}/{}/".format(PINTEREST_HOST, path))
    root = html.fromstring(r.content)
    tag = root.xpath("//script[@id='initial-state']")[0]
    responses = json.loads(tag.text)["resourceResponses"]

    result = UserProfileResources()

    for item in responses:

        if item["name"] == 'UserProfileBaseResource':
            result.UserProfileBaseResource.status = item["response"]["status"]
            result.UserProfileBaseResource.status_code = item["response"]["http_status"]
            result.UserProfileBaseResource.data = item["response"]["data"]

        if item["name"] == 'UserProfileBoardResource':
            result.UserProfileBoardResource.status = item["response"]["status"]
            result.UserProfileBoardResource.status_code = item["response"]["http_status"]
            result.UserProfileBoardResource.data = item["response"]["data"]

        if response_has_errors(item):
            result.error = response_error_message(item)
    return result


def user_boards(username: str) -> List[Board]:
    """
    Retrieves list of boards

    :param username:
    :return:
    :raises UserBoardException
    """
    data = get_page_data(username)

    if data.error is not None:
        raise UserBoardException(data.error)

    result = data.UserProfileBoardResource
    result.data = user_profile_board_resource(result.data)

    if len(result.data) > 0:
        return result.data

    raise UserBoardException("User does not have any boards")


def get_download_links(board: Board) -> List[DownloadableResource]:
    """
    Get downloadable links for board resources

    :param board: User board
    :return: List of downloadable resources
    """
    s = session()
    bookmark = None
    resources = []

    while bookmark != '-end-':
        options = {
            "board_id": board.id,
            "page_size": 25,
        }

        if bookmark:
            options.update({
                "bookmarks": [bookmark],
            })

        r = s.get("{}/resource/BoardFeedResource/get/".format(PINTEREST_HOST), params={
            "source_url": board.url,
            "data": json.dumps({
                "options": options,
                "context": {},
            }),
        })

        data = r.json()
        resources += data["resource_response"]["data"]
        bookmark = data["resource"]["options"]["bookmarks"][0]

    originals: List[DownloadableResource] = []
    for res in resources:
        # Get original image url
        if ("images" in res) and (res["videos"] is None):

            image = DownloadableResource()
            image.type = DownloadableResourceType.image
            image.id = res["id"]
            image.url = res["images"]["orig"]["url"]

            originals.append(image)
        # Get video download url
        if "videos" in res and (res["videos"] is not None):
            video = DownloadableResource()
            video.type = DownloadableResourceType.video
            video.id = res["id"]
            video.url = res["videos"]["video_list"]["V_HLSV4"]["url"]

            originals.append(video)

    return originals


def fetch_image(url: str, save_path: str) -> None:
    """
    Downloads image resource

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


def get_stream_urls(url: str) -> List:
    """
    Picks a stream with best resolution from provided url
    Requests that playlist and returns list of streams
    """
    r: Response = requests.get(url, stream=True)
    best_quality: str = ""

    line: bytes
    for line in r.iter_lines():
        decoded_url: str = line.decode("utf-8")

        if (not decoded_url) or (not decoded_url.endswith("m3u8")):
            continue

        best_quality = decoded_url

    splitted_url: list = url.split("/")
    splitted_url[-1]: str = best_quality
    url: str = "/".join(splitted_url)

    streams: Response = requests.get(url, stream=True)
    stream_urls: List = []

    for line in streams.iter_lines():
        decoded_url: str = line.decode("utf-8")
        if (not decoded_url) or (not decoded_url.endswith("ts")):
            continue

        stream_url: list = url.split("/")
        stream_url[-1] = decoded_url
        stream_urls.append("/".join(stream_url))

    return stream_urls


def fetch_video(playlist_url: str, save_path: str) -> None:
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


def fetch_board(board_name: str,
                links: List[DownloadableResource],
                save_folder: str,
                force_download: bool = False) -> None:
    """
    Downloads Pinterest board resources

    :param board_name: Pinterest board name
    :param links: Pinterest board
    :param save_folder: Folder where to save
    :param force_download: Forces re-download of resource
    :return:
    """
    if not links:
        raise ValueError("Links parameter cannot be empty")

    if not save_folder:
        raise ValueError("Folder parameter is empty")

    if not isinstance(links, list):
        raise TypeError("Links has wrong type")

    print(f"Downloading {board_name}")
    links_with_progress: List[DownloadableResource] = Bar("Progress").iter(links)

    for resource in links_with_progress:
        # Download images
        if resource.type == DownloadableResourceType.image:
            ext = resource.url.split(".")[-1]
            filename = f"{resource.id}.{ext}"
            save_path = os.path.join(save_folder, filename)
            path_exists = os.path.exists(save_path)
            if not path_exists or force_download:
                make_dir(save_folder)
                fetch_image(resource.url, save_path)

        # Download video
        if resource.type == DownloadableResourceType.video:
            filename = f"{resource.id}.ts"
            save_path = os.path.join(save_folder, filename)
            path_exists = os.path.exists(save_path)

            if not path_exists or force_download:
                make_dir(save_folder)
                fetch_video(resource.url, save_path)


def session() -> Session:
    """
    Returns request session with pre-defined headers
    """
    s = requests.Session()
    s.headers = {
        "Referer": PINTEREST_HOST,
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 "
                      "Safari/537.36",
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


def make_dir(directory: str) -> None:
    """
    Creates directory if not exists
    """
    try:
        os.makedirs(directory)
    except OSError:
        pass


def log(e: Exception, header: str = None) -> None:
    """
    Logs exceptions to stdout
    """
    if header:
        print(f"{header} {str(e)}")
    else:
        print(f"{str(e)}")

    if traceback:
        print("Traceback:")
        print("".join(traceback.format_tb(e.__traceback__)))


def main() -> None:
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
            links = get_download_links(board)
            save_folder_name = os.path.join(args.save_folder, board.owner, board.name)
            fetch_board(board.name, links, save_folder_name, args.force)

    except Exception as e:
        log(e)


if __name__ == "__main__":
    main()
