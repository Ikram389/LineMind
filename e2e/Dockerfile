# Screenshots and accessibility checks (Playwright) with Alpine's own Chromium:
# small, and no separate browser download.
FROM node:22-alpine
RUN apk add --no-cache chromium nss freetype harfbuzz ttf-freefont font-noto font-noto-emoji
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    CHROMIUM_PATH=/usr/bin/chromium-browser
WORKDIR /e2e
