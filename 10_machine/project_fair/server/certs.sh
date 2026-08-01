#!/bin/bash
# Local HTTPS for the kiosk, so the iPad will hand over the camera.
#
# This is not about secrecy. getUserMedia -- the live viewfinder -- only exists
# in a secure context, and http://something.local:5050 is not one, so Safari
# refuses the camera outright. With certs the kiosk gets a real preview, an
# oval framing guide and a countdown. Without them it falls back to the native
# camera sheet, which works fine but has none of that.
#
# Run this once. It needs mkcert:
#
#     brew install mkcert
#     mkcert -install        <- asks for your password, adds the local root CA
#
# Then: ./certs.sh

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="$(scutil --get LocalHostName)"

if ! command -v mkcert > /dev/null; then
  echo "mkcert is not installed. Run:"
  echo "    brew install mkcert && mkcert -install"
  exit 1
fi

mkdir -p "$HERE/certs"

# Every name the iPad might use to reach this laptop. A cert that does not
# cover the exact hostname typed into Safari is a cert Safari will reject.
mkcert -cert-file "$HERE/certs/cert.pem" \
       -key-file  "$HERE/certs/key.pem" \
       "$NAME.local" "$NAME" localhost 127.0.0.1 ::1

echo
echo "done. the kiosk is now at:  https://$NAME.local:5050/"
echo
echo "On the iPad, once:"
echo "  1. AirDrop or email yourself:  $(mkcert -CAROOT)/rootCA.pem"
echo "  2. Open it -> Settings shows 'Profile Downloaded' -> Install"
echo "  3. Settings > General > About > Certificate Trust Settings"
echo "     -> turn ON full trust for the mkcert root"
echo
echo "Step 3 is the one everyone forgets. Installing the profile is not enough;"
echo "iOS keeps the root untrusted until you flip that switch."
