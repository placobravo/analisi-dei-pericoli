const versionPicker = document.querySelector("[data-catalog-version-picker]");

if (versionPicker) {
  versionPicker.elements.versione.addEventListener("change", () => versionPicker.requestSubmit());
}
