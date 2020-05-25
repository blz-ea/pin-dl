import os
import sys
import pytest
from .__init__ import make_dir, log

test_board = ""
test_image = ""
test_video = ""
test_user = ""
test_folder = "test_pinterest_download_folder"

# @pytest.fixture(scope="module") # module, package, function, class, session
# def api_connection():
#   return

# @pytest.mark.skipif(condition)
# @pytest.mark.xfail(condition, reason=None, run=True, raises=None) # Mark as expected to fail

# @pytest.fixture
# def even_number():
#   return 2

@pytest.fixture(scope="session", autouse=True)
def session_start(request):
  print("\nStarting tests")
  
  def session_end():
    print("\nFinishing tests")
  
  request.addfinalizer(session_end)


@pytest.fixture(scope="session")
def remove_test_folder(request):
  request.addfinalizer(lambda: os.rmdir(test_folder))


@pytest.mark.usefixtures("remove_test_folder")
def test_make_dir():
  make_dir(test_folder)
  assert os.path.exists(test_folder)

def test_log(capfd):
  try:
    raise ValueError("Testing log")
  except Exception as e:
    log("[Test]", e)
    out, err = capfd.readouterr()
    assert out == "[Test] Testing log\n"