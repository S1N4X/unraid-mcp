#!/usr/bin/env bash
# Deploy unraid-mcp to monolith: build the image locally, ship it over ssh,
# install the canonical dockerMan template (deploy/my-unraid-mcp.xml) and
# rebuild the container on host networking bound to 10.10.10.50:8078 (#360).
#
# Every docker/ssh call goes through run(), except the image-ID read after the
# build; --dry-run prints each command and remote script (prefixed DRY-RUN:)
# and never calls docker or ssh.
set -euo pipefail

MONOLITH=${MONOLITH:-root@192.168.0.50}
readonly MONOLITH
readonly NAME=unraid-mcp
readonly IMAGE=unraid-mcp:latest
readonly TEMPLATE=/boot/config/plugins/dockerMan/templates-user/my-unraid-mcp.xml
readonly AUTOSTART=/var/lib/docker/unraid-autostart
# shellcheck disable=SC2034  # read only through remote_header's ${!var}
readonly APPDATA=/mnt/user/appdata/unraid-mcp
# shellcheck disable=SC2034  # read only through remote_header's ${!var}
readonly APP_UID_GID=10078:10078
readonly BIND=10.10.10.50:8078
readonly REBUILD=/usr/local/emhttp/plugins/dynamix.docker.manager/scripts/rebuild_container
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
readonly REPO_ROOT
readonly LOCAL_TEMPLATE="$REPO_ROOT/deploy/my-unraid-mcp.xml"
readonly SSH=(ssh -o BatchMode=yes "$MONOLITH")
readonly STEPS=9

usage() {
    cat <<EOF
Usage: deploy/deploy.sh --backup-suffix SUFFIX [--dry-run]

Deploy unraid-mcp to $MONOLITH (override with MONOLITH=user@host):
preflight, build, backup, ship, template, secrets, autostart, rebuild, verify.

  --backup-suffix SUFFIX  required; before any change the template and
                          autostart are copied to <file>.bak-SUFFIX, the
                          appdata/secret owners and modes are recorded in
                          $AUTOSTART.bak-SUFFIX.owners and the
                          running image is tagged unraid-mcp:bak-SUFFIX
                          (refuses to overwrite). SUFFIX matches
                          ^[A-Za-z0-9][A-Za-z0-9._-]*\$, at most 100 chars
  --dry-run               print every command and remote script, run nothing
  -h, --help              show this help
EOF
}

usage_error() {
    printf 'deploy.sh: %s\n' "$1" >&2
    usage >&2
    exit 2
}

die() {
    printf 'deploy.sh: %s\n' "$1" >&2
    exit 1
}

DRY_RUN=0
SUFFIX=
while (($#)); do
    case $1 in
        --backup-suffix)
            (($# >= 2)) || usage_error "--backup-suffix needs a value"
            SUFFIX=$2
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *) usage_error "unknown argument: $1" ;;
    esac
done
suffix_re='^[A-Za-z0-9][A-Za-z0-9._-]*$'
[[ -n $SUFFIX ]] || usage_error "--backup-suffix is required"
[[ $SUFFIX =~ $suffix_re ]] || usage_error "invalid --backup-suffix: $SUFFIX"
((${#SUFFIX} <= 100)) || usage_error "--backup-suffix longer than 100 chars"
readonly DRY_RUN SUFFIX
# Previous image, kept under its own tag because step 4 loads over $IMAGE.
readonly BAK_IMAGE=unraid-mcp:bak-$SUFFIX
# "uid:gid mode path" of $APPDATA and both secrets before step 6 changes them.
# Next to the autostart backup: /var/lib/docker is root-only, outlives a
# reboot, and stays outside the appdata tree whose ownership step 6 changes.
readonly OWNERS_BAK=$AUTOSTART.bak-$SUFFIX.owners

quote() {
    local out
    printf -v out '%q ' "$@"
    printf '%s' "${out% }"
}

dry() {
    printf 'DRY-RUN: %s\n' "$1"
}

# The only place docker or ssh is invoked, apart from the image-ID read in
# step 2.
#   run CMD...                    run CMD
#   run --stdin-text TEXT CMD...  run CMD with TEXT on stdin
#   run --stdin-file FILE CMD...  run CMD with FILE on stdin
#   run --stdin-save CMD...       run CMD with `docker save $IMAGE` on stdin
run() {
    local mode=none src=
    case $1 in
        --stdin-text | --stdin-file)
            mode=$1
            src=$2
            shift 2
            ;;
        --stdin-save)
            mode=$1
            shift
            ;;
    esac
    if ((DRY_RUN)); then
        case $mode in
            none) dry "$(quote "$@")" ;;
            --stdin-text)
                dry "$(quote "$@") <<'SCRIPT'"
                while IFS= read -r line; do dry "  $line"; done <<<"$src"
                dry "SCRIPT"
                ;;
            --stdin-file) dry "$(quote "$@") < $(quote "$src")" ;;
            --stdin-save) dry "$(quote docker save "$IMAGE") | $(quote "$@")" ;;
        esac
        return 0
    fi
    case $mode in
        none) "$@" ;;
        --stdin-text) "$@" <<<"$src" ;;
        --stdin-file) "$@" <"$src" ;;
        --stdin-save) docker save "$IMAGE" | "$@" ;;
    esac
}

# Remote script prologue: strict mode plus the named constants, %q-quoted.
remote_header() {
    local var
    printf 'set -euo pipefail\n'
    for var in "$@"; do
        printf '%s=%q\n' "$var" "${!var}"
    done
}

# remote BODY VAR...: run BODY on monolith via `ssh bash -s`, with VAR... defined.
# The body sits in one { } </dev/null group so bash parses all of it before
# running anything and no remote command can swallow the rest of the script.
remote() {
    local body=${1#$'\n'}
    shift
    run --stdin-text "$(remote_header "$@")"$'\n{\n'"$body"$'\n} </dev/null' \
        "${SSH[@]}" bash -s
}

CURRENT_STEP=
step() {
    CURRENT_STEP=$2
    printf '==> [%d/%d] %s\n' "$1" "$STEPS" "$2"
}

# restore_hint WHAT: after a failure from step 3 (backup) on, print the
# backups and the commands that put the previous template, autostart, secret
# ownership and image back.  The previous image ran as root, so the secrets
# must be owned by root again before the rebuild or it refuses to start.
restore_hint() {
    cat >&2 <<EOF
deploy.sh: step $1 failed on $MONOLITH; this run may have changed it.
backups (a backup step that had not run yet is absent):
  $TEMPLATE.bak-$SUFFIX
  $AUTOSTART.bak-$SUFFIX
  $OWNERS_BAK
  image $BAK_IMAGE (absent if no $IMAGE existed before this deploy)
restore (on $MONOLITH):
  cp -- $TEMPLATE.bak-$SUFFIX $TEMPLATE
  cp -- $AUTOSTART.bak-$SUFFIX $AUTOSTART
  while read -r owner mode path; do chown -- "\$owner" "\$path"; chmod -- "\$mode" "\$path"; done <$OWNERS_BAK
  docker tag $BAK_IMAGE $IMAGE
  $REBUILD $NAME
if $OWNERS_BAK is missing, the previous root-run image needs:
  chown 0:0 $APPDATA $APPDATA/http-token $APPDATA/unraid-api.key
  chmod 700 $APPDATA
  chmod 600 $APPDATA/http-token $APPDATA/unraid-api.key
EOF
}

# Set once step 3 starts: any later failure (set -e or explicit) prints the
# restore commands on the way out.
BACKUP_STARTED=0
on_exit() {
    local status=$?
    if ((status != 0 && BACKUP_STARTED)); then
        restore_hint "$CURRENT_STEP"
    fi
}
trap on_exit EXIT

((DRY_RUN)) && echo "dry run: nothing is executed on $MONOLITH or by docker"
echo "target: $MONOLITH  container: $NAME  bind: $BIND  backup suffix: $SUFFIX"

step 1 preflight
for tool in docker ssh; do
    command -v "$tool" >/dev/null || die "preflight: $tool not found on PATH"
done
[[ -f $LOCAL_TEMPLATE ]] || die "preflight: missing $LOCAL_TEMPLATE"
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '
problems=()
[[ -x $REBUILD ]] || problems+=("not executable: $REBUILD")
for f in "$TEMPLATE" "$AUTOSTART" "$APPDATA/http-token" "$APPDATA/unraid-api.key"; do
    if [[ ! -f $f || -L $f ]]; then problems+=("not a regular file: $f"); fi
done
if [[ ! -d $APPDATA || -L $APPDATA ]]; then problems+=("not a directory: $APPDATA"); fi
for f in "$TEMPLATE.bak-$SUFFIX" "$AUTOSTART.bak-$SUFFIX" "$OWNERS_BAK"; do
    if [[ -e $f || -L $f ]]; then problems+=("backup already exists: $f"); fi
done
if docker image inspect "$BAK_IMAGE" >/dev/null 2>&1; then
    problems+=("backup image already exists: $BAK_IMAGE")
fi
if ((${#problems[@]})); then
    printf "preflight: %s\n" "${problems[@]}" >&2
    exit 1
fi
echo "preflight ok"' \
    REBUILD TEMPLATE AUTOSTART APPDATA SUFFIX BAK_IMAGE OWNERS_BAK ||
    die "preflight failed on $MONOLITH; this run changed nothing. An existing
backup means a previous run may have left backups and the $BAK_IMAGE tag:
choose a new --backup-suffix or remove them"

step 2 build
run docker build -t "$IMAGE" "$REPO_ROOT"
# Pin the build by ID: the tag is mutable (another build on this daemon can
# move it), so ship checks the loaded image and verify the running one.
if ((DRY_RUN)); then
    dry "$(quote docker image inspect -f '{{.Id}}' "$IMAGE")"
    IMAGE_ID='<built-image-id>'
else
    IMAGE_ID=$(docker image inspect -f '{{.Id}}' "$IMAGE")
    [[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ ]] || die "build: unexpected image ID: $IMAGE_ID"
fi
readonly IMAGE_ID
echo "build: $IMAGE is $IMAGE_ID"

step 3 backup
# Before ship: the docker load in step 4 moves $IMAGE to the new image, so the
# previous one is tagged $BAK_IMAGE here.
# Plain cp, no -p: /boot is vfat and cannot keep ownership/modes.
# Owners/modes of the appdata dir and secrets are recorded (no contents read)
# for the restore commands, since step 6 changes them.
BACKUP_STARTED=1
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '
for f in "$TEMPLATE.bak-$SUFFIX" "$AUTOSTART.bak-$SUFFIX" "$OWNERS_BAK"; do
    if [[ -e $f || -L $f ]]; then
        echo "backup: refusing to overwrite $f" >&2
        exit 1
    fi
done
if docker image inspect "$BAK_IMAGE" >/dev/null 2>&1; then
    echo "backup: refusing to overwrite image $BAK_IMAGE" >&2
    exit 1
fi
for f in "$TEMPLATE" "$AUTOSTART"; do
    cp -- "$f" "$f.bak-$SUFFIX"
    echo "backup: $f.bak-$SUFFIX"
done
stat -c "%u:%g %a %n" "$APPDATA" "$APPDATA/http-token" "$APPDATA/unraid-api.key" >"$OWNERS_BAK"
echo "backup: $OWNERS_BAK"
cat -- "$OWNERS_BAK"
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    docker tag "$IMAGE" "$BAK_IMAGE"
    echo "backup: image $IMAGE tagged $BAK_IMAGE"
else
    echo "backup: no $IMAGE on this host, no image to keep"
fi' \
    TEMPLATE AUTOSTART SUFFIX IMAGE BAK_IMAGE APPDATA OWNERS_BAK

step 4 ship
run --stdin-save "${SSH[@]}" docker load
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '
loaded=$(docker image inspect -f "{{.Id}}" "$IMAGE")
if [[ $loaded != "$IMAGE_ID" ]]; then
    echo "ship: $IMAGE here is $loaded, expected the build $IMAGE_ID" >&2
    exit 1
fi
echo "ship: $IMAGE is $IMAGE_ID"' \
    IMAGE IMAGE_ID

step 5 template
# Stdin carries the XML, so the script goes in as one bash -c argument.
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
upload_script="$(remote_header TEMPLATE)"'
cat >"$TEMPLATE.new"
mv -f "$TEMPLATE.new" "$TEMPLATE"
echo "template: installed $TEMPLATE"'
run --stdin-file "$LOCAL_TEMPLATE" "${SSH[@]}" "bash -c $(printf '%q' "$upload_script")"

step 6 secrets
# Ownership and modes only; the secret contents are never read.
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '
files=("$APPDATA/http-token" "$APPDATA/unraid-api.key")
chown "$APP_UID_GID" "$APPDATA" "${files[@]}"
chmod 700 "$APPDATA"
chmod 600 "${files[@]}"
stat -c "%u:%g %a %n" "$APPDATA" "${files[@]}"' \
    APPDATA APP_UID_GID

step 7 autostart
# Must precede rebuild: rebuild_container stops containers not in autostart.
# Append only; existing lines are never rewritten or reordered.
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '
if awk -v n="$NAME" '"'"'$1 == n { found = 1 } END { exit !found }'"'"' "$AUTOSTART"; then
    echo "autostart: $NAME already listed"
else
    if [[ -s $AUTOSTART && -n $(tail -c 1 "$AUTOSTART") ]]; then
        printf "\n" >>"$AUTOSTART"
    fi
    printf "%s\n" "$NAME" >>"$AUTOSTART"
    echo "autostart: appended $NAME"
fi' \
    NAME AUTOSTART

step 8 rebuild
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '"$REBUILD" "$NAME"' REBUILD NAME

step 9 verify
# shellcheck disable=SC2016  # remote script: expands on monolith, not here
remote '
listen=
for ((i = 0; i < 30; i++)); do
    running=$(docker inspect -f "{{.State.Running}}" "$NAME" 2>/dev/null || true)
    if [[ $running == true ]]; then
        pid=$(docker inspect -f "{{.State.Pid}}" "$NAME" 2>/dev/null || true)
        listen=$(ss -ltnpH | awk -v p="pid=$pid," '"'"'index($0, p) { print $4 }'"'"' |
            sort -u | paste -sd " " -)
        if [[ $listen == "$BIND" ]]; then
            echo "listener: $listen (pid $pid)"
            image=$(docker inspect -f "{{.Image}}" "$NAME")
            if [[ $image != "$IMAGE_ID" ]]; then
                echo "verify: $NAME runs image $image, expected the build $IMAGE_ID" >&2
                exit 1
            fi
            echo "image: $image"
            docker inspect -f "NetworkMode={{.HostConfig.NetworkMode}} User={{.Config.User}} ReadonlyRootfs={{.HostConfig.ReadonlyRootfs}}" "$NAME"
            exit 0
        fi
    fi
    sleep 1
done
echo "verify: after 30 s running=${running:-?} listeners=${listen:-none}, expected exactly $BIND" >&2
docker logs --tail 50 "$NAME" 2>&1 || true
exit 1' \
    NAME BIND IMAGE_ID

if ((DRY_RUN)); then
    echo "dry run complete: nothing was changed"
else
    echo "deployed: $NAME listening on $BIND"
fi
echo "live smoke: UNRAID_MCP_LIVE_URL=http://$BIND uv run pytest tests/test_live_http.py --no-cov"
