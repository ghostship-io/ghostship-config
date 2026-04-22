FROM ghcr.io/dgtlmoon/changedetection.io:latest

ENV CLOAKBROWSER_BINARY_PATH=/opt/cloakbrowser/chrome
ENV CLOAKBROWSER_WRAPPER=true

COPY cloakbrowser/common/install_cloakbrowser.py /tmp/install_cloakbrowser.py
COPY changedetection-cloakbrowser/ghostship_cloakbrowser.py /app/changedetectionio/content_fetchers/ghostship_cloakbrowser.py
COPY changedetection-cloakbrowser/patch_changedetection.py /tmp/patch_changedetection.py

RUN pip install --no-cache-dir cloakbrowser         && python /tmp/install_cloakbrowser.py         && python /tmp/patch_changedetection.py         && python -m py_compile             /app/changedetectionio/content_fetchers/ghostship_cloakbrowser.py             /app/changedetectionio/content_fetchers/__init__.py             /app/changedetectionio/blueprint/ui/edit.py             /app/changedetectionio/forms.py
