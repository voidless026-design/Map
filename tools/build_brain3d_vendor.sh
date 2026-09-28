#!/usr/bin/env bash
# Rebuild openatlas/web/static/vendor/brain3d.vendor.js - one offline bundle of three.js,
# 3d-force-graph, UnrealBloomPass and three-spritetext (all MIT/ISC/BSD), exposed as globals
# (ForceGraph3D, THREE, UnrealBloomPass, SpriteText) so the 3D brain works with no CDN.
set -euo pipefail
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
cd "$work"
echo '{ "name": "oa-brain3d-vendor", "private": true }' > package.json
npm install -q --no-audit --no-fund 3d-force-graph@1.80.0 three@0.186.1 three-spritetext@1.10.0 esbuild
cat > entry.js <<'JS'
import ForceGraph3D from "3d-force-graph";
import * as THREE from "three";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import SpriteText from "three-spritetext";
Object.assign(window, { ForceGraph3D, THREE, UnrealBloomPass, SpriteText });
JS
npx esbuild entry.js --bundle --minify --format=iife --target=es2020 --legal-comments=eof \
  --outfile="$OLDPWD/openatlas/web/static/vendor/brain3d.vendor.js"
