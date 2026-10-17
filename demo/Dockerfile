FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

# ffmpeg for the 1080p -> 720p delivery pass
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# The app itself runs inside this container (two sessions, two ports), so the
# image carries the app's runtime. pyarrow is pinned because connector 4.7.5
# rejects >=24 - the same pin the repo uses.
#
# playwright is installed explicitly, into the interpreter the ENTRYPOINT uses:
# the image's default `python` did not have it importable, and the version must
# match the image tag so it uses the browsers already at /ms-playwright.
RUN python -m pip install --no-cache-dir \
      playwright==1.55.0 \
      streamlit==1.66.0 \
      snowflake-connector-python==4.7.5 \
      pyarrow==23.0.1 \
      python-dotenv==1.2.2

WORKDIR /workspace
COPY . /demo
ENTRYPOINT ["python", "/demo/runner.py"]
