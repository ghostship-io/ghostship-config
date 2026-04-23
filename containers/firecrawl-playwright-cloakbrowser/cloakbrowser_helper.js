async function launchCloak(options) {
  const load = new Function("specifier", "return import(specifier);");
  const mod = await load("cloakbrowser");
  return mod.launch(options);
}

module.exports = { launchCloak };
