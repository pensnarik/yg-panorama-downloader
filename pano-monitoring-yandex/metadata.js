/* Capture the provider's data without guessing undocumented projection semantics. */
const PanoramaMetadata = (() => {
  function parseResponse(text) {
    const source = text.replace(/^\uFEFF/, "").trim();
    try {
      return JSON.parse(source);
    } catch (error) {
      // Older endpoints can wrap JSON in a callback. Never execute the callback.
      const jsonp = source.match(/^[\w$]+(?:\.[\w$]+)*\s*\(([\s\S]*)\)\s*;?$/);
      if (!jsonp) throw error;
      return JSON.parse(jsonp[1]);
    }
  }

  function makeCapture(rawResponse, sourceUrl, capturedAt) {
    const data = rawResponse?.data?.Data;
    if (rawResponse.status !== "success" || !data?.Images?.imageId || !data.panoramaId) {
      throw new Error("Response contains no panorama metadata");
    }
    return {
      schemaVersion: 1,
      provider: "yandex",
      imageId: data.Images.imageId,
      panoramaId: data.panoramaId,
      capturedAt,
      sourceUrl,
      rawResponse
    };
  }

  return { parseResponse, makeCapture };
})();

if (typeof module !== "undefined") module.exports = PanoramaMetadata;
