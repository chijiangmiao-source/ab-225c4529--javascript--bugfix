# One-shot real-browser acceptance image.
#
# Context is the whole frontend/ directory (see docker-compose.yml): the
# scenario script imports the application's own exact-integer module
# (src/intmath.js) so the regression parses captured responses with the same
# lossless parser the page ships.  Chromium and its OS dependencies are
# installed for Playwright; this image is NOT used to serve the page.
FROM node:20-bookworm-slim

WORKDIR /app

# Runs headless Chromium as root in the container.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install dependencies first for better layer caching.  Skip Playwright's
# post-install download (all three browser engines); install only Chromium
# plus its OS libraries explicitly below.
COPY e2e/package.json e2e/package-lock.json ./e2e/
RUN cd e2e \
    && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --no-audit --no-fund \
    && npx playwright install --with-deps chromium

# Application sources consumed by the scenario and the exact-integer tests.
COPY src ./src
COPY e2e ./e2e

# Stage 1: pure-Node exact-integer unit tests; stage 2: real-browser page
# submission regression.  Non-zero exit from either stage fails the service.
ENTRYPOINT ["e2e/entrypoint.sh"]
CMD ["http://web:80"]
