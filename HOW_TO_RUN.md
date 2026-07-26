# How to run BirdTrip on your Mac

You don't need to write or read any code to do this. You're just installing
two free, standard tools (if you don't already have them) and running one
script.

## Step 1 — Unzip the folder

Double-click the `.zip` file you downloaded. It'll create a `birdtrip-app`
folder. Move it wherever you like (Desktop is fine).

## Step 2 — Open Terminal

Terminal is a built-in Mac app. The easiest way to find it: press
`Cmd + Space`, type "Terminal", press Enter.

## Step 3 — Go to the folder

In the Terminal window, type `cd ` (with a trailing space), then drag the
`birdtrip-app` folder from Finder into the Terminal window — it'll
auto-fill the path. Press Enter. You should now be "inside" that folder.

## Step 4 — Run the start script

Type this and press Enter:

```
./start.sh
```

The first time you run this, it will check whether your Mac has Python and
Node.js installed.

- **If it stops and tells you to install something** (Python or Node), it
  will print the exact command to run — it's a one-time install, just like
  installing any other app. The easiest path for both is installing
  [Homebrew](https://brew.sh) first (one command, shown on that site), then
  running the command the script gave you (`brew install python@3.12` or
  `brew install node`). Once that finishes, run `./start.sh` again.
  Note: many Macs already have a `python3` command, but it's often a very
  old version (3.9) that Apple bundles with its developer tools — this app
  needs 3.10 or newer, so the script specifically checks for that and will
  ask you to install a current version via Homebrew if needed, rather than
  using the old one.
- **If everything's already installed**, it'll download the app's own
  packages (only happens once — this can take a couple of minutes the very
  first time, then it's fast from then on), start the app, load some sample
  bird-watching data so you have something to look at, and open your
  browser automatically.

## Step 5 — Look around

Your browser should open to the app itself, showing a couple of sample
outings (fake bird walks with real-looking data) — click one to see the
species list. Since this is sample data with no photos attached, you won't
see matched photos yet, but you'll see the outing/species side of things
working.

If you want to see the technical side (the auto-generated API
documentation, which is a nice thing to show off in an interview), open a
second browser tab to: `http://localhost:8000/docs`

## Step 6 — Stop it

Go back to the Terminal window and press `Ctrl + C`. That shuts both parts
of the app down cleanly. Nothing keeps running in the background.

## Using your own real data (optional, later)

Right now the app is running on made-up sample data so you can see it work
immediately. To use your own eBird checklists and Flickr photos instead:

1. **eBird**: get a personal key at https://ebird.org/api/keygen, and export
   your checklist history from https://ebird.org/downloadMyData.
2. **Flickr**: create an app at
   https://www.flickr.com/services/apps/create/ to get a key and secret.
3. Open `backend/.env` in any text editor and fill in the values (there are
   comments in the file explaining each one).
4. On the `/docs` page (`http://localhost:8000/docs`), use the `/sync/ebird`
   endpoint to upload your real CSV export instead of the sample one, and
   `/sync/flickr` to pull your photos for a date range, then `/sync/match`
   to re-run the matching.

None of this is required just to see the app working — it's only needed if
you want to demo it with your own real outings and photos.

## If something goes wrong

- **"permission denied" when running `./start.sh`**: run
  `chmod +x start.sh` once, then try again.
- **A message about port 8000 or 5173 already being in use**: something
  else on your Mac is already using that port. Quit whatever that is (or
  restart your Mac) and try again.
- **`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
  in `backend.log`**: this means the script used an old Python version
  (usually the 3.9 Apple bundles with Xcode tools) instead of a modern one.
  The latest version of `start.sh` checks for this automatically and will
  tell you to run `brew install python@3.12` if it can't find a good
  enough version — make sure you're running the newest copy of this
  folder, then try `./start.sh` again.
- **Anything else**: check `backend.log` in the `birdtrip-app` folder — it
  usually says exactly what went wrong. You're also welcome to paste that
  into a Claude chat and ask what it means.
