#!/usr/bin/env bash
# Full build script — run from repo root.
# Set as the Render "Build Command": bash build.sh
set -e

echo "==> Building React frontend..."
cd frontend
npm install --legacy-peer-deps
npx vite build   # call vite directly to skip strict tsc type-checking
cd ..
rm -rf backend/frontend_dist
cp -r frontend/dist backend/frontend_dist
echo "==> Frontend built ($(ls backend/frontend_dist | wc -l | tr -d ' ') root files)"

echo "==> Installing Python backend..."
cd backend
pip install -e .

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Build complete."
