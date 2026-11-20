set -u
A="-o Dir::State=$HOME/apt/state -o Dir::Cache=$HOME/apt/cache -o Dir::State::status=/var/lib/dpkg/status -o Debug::NoLocking=1"
mkdir -p ~/apt/state/lists/partial ~/apt/cache/archives/partial ~/chromelibs ~/debs
apt-get $A update -qq 2>&1 | tail -1
C=$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome | tail -1)
cd ~/debs
for round in 1 2 3 4; do
  missing=$(LD_LIBRARY_PATH=$HOME/chromelibs/usr/lib/x86_64-linux-gnu:$HOME/chromelibs/lib/x86_64-linux-gnu ldd $C | awk '/not found/{print $1}')
  [ -z "$missing" ] && { echo "ALL_LIBS_OK round $round"; break; }
  pkgs=""
  for l in $missing; do
    case $l in
      libnspr4*) p=libnspr4;; libnss3*|libnssutil3*|libsmime3*) p=libnss3;; libatk-1.0*) p=libatk1.0-0;;
      libatk-bridge*) p=libatk-bridge2.0-0;; libdbus-1*) p=libdbus-1-3;; libcups*) p=libcups2;;
      libxkbcommon*) p=libxkbcommon0;; libasound*) p=libasound2;; libgbm*) p=libgbm1;;
      libXcomposite*) p=libxcomposite1;; libXdamage*) p=libxdamage1;; libXfixes*) p=libxfixes3;;
      libXrandr*) p=libxrandr2;; libatspi*) p=libatspi2.0-0;; libavahi-common*) p=libavahi-common3;;
      libavahi-client*) p=libavahi-client3;; libwayland-server*) p=libwayland-server0;; libdrm*) p=libdrm2;;
      libXi.so*) p=libxi6;; libXext*) p=libxext6;; libXrender*) p=libxrender1;; libxcb-randr*) p=libxcb-randr0;;
      libX11.so*) p=libx11-6;; libxcb.so*) p=libxcb1;; libXau*) p=libxau6;; libXdmcp*) p=libxdmcp6;;
      libexpat*) p=libexpat1;; libgnutls*) p=libgnutls30;; libsystemd*) p=libsystemd0;;
      *) p=$(apt-file search -l "$l" 2>/dev/null | head -1); [ -z "$p" ] && echo "UNKNOWN $l";;
    esac
    [ -n "${p:-}" ] && pkgs="$pkgs $p"
  done
  apt-get $A download $(echo $pkgs | tr ' ' '\n' | sort -u) 2>&1 | grep -v "^Get" | tail -2
  for d in *.deb; do dpkg -x "$d" ~/chromelibs; done
done
LD_LIBRARY_PATH=$HOME/chromelibs/usr/lib/x86_64-linux-gnu:$HOME/chromelibs/lib/x86_64-linux-gnu ldd $C | grep "not found" | head
echo 'export LD_LIBRARY_PATH=$HOME/chromelibs/usr/lib/x86_64-linux-gnu:$HOME/chromelibs/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}' > ~/chromelibs.env
