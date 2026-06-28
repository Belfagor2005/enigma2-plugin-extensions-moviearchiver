<p align="center">
  <img src="https://raw.github.com/MovieArchiver/enigma2-plugin-extensions-moviearchiver/master/src/plugin.png" alt="Screenshot">
</p>

<p align="center">
  <a href="https://github.com/Belfagor2005">
    <img src="https://komarev.com/ghpvc/?username=Belfagor2005&label=Repository%20Views&color=blueviolet" alt="Visitors">
  </a>
</p>

<p align="center">
  <a href="https://ko-fi.com/lululla">
    <img src="https://img.shields.io/badge/_-Donate-red.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge" alt="Ko-fi">
  </a>

  <a href="https://paypal.me/belfagor2005">
    <img src="https://img.shields.io/badge/_-Donate-green.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge" alt="PayPal">
  </a>
</p>


# 📦 MovieArchiver

---

## 📁 Archiving

MovieArchiver automatically archives recordings from the internal hard drive (e.g. HDD) to an external USB drive.

If multiple storage devices are used, this ensures that the recording drive always has enough free space for new recordings.

When **Automatic Archiving** is enabled, after each recording the system checks whether the configured storage limit has been reached.  
If necessary, older recordings are moved to the archive until enough free space is available again.

### Supported file extensions for archiving:
- `.ts`
- `.avi`
- `.mkv`
- `.mp4`
- `.iso`

### Included metadata files:
- `.ts.cuts`
- `.ts.meta`

---

## 💾 Backup Mode

Alternatively, MovieArchiver can also be used as a backup tool (configurable in settings).

In backup mode, all files inside the selected directory (including all subfolders) are added, **without file extension restrictions**.

---

## ⚙️ Manual Mode

If automatic mode is disabled, MovieArchiver can still be started manually via the settings page.

---

## ⚠️ Important Notice

- Use this script at your own risk.

---

## 🧪 Testing Notes

The following scenarios should be tested:

- What happens if EMC is open while an archive process starts in the background?
- What happens if a recording is being played while it is being archived?

---

## 🧩 Tested Images / Receivers

- openATV / Gigablue Quad  
- HDF / ET9000  

---

## 📸 Screenshot

<p align="center">
  <img src="https://raw.github.com/MovieArchiver/enigma2-plugin-extensions-moviearchiver/master/screenshots/MovieArchiver.jpg" alt="MovieArchiver Screenshot">
</p>

