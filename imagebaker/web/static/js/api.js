/**
 * ImageBaker Web - API Client
 */
(function(window) {
  "use strict";

  async function apiGet(path) {
    const res = await fetch(path, {
      headers: { "Accept": "application/json" }
    });
    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  }

  async function apiPost(path, payload = {}) {
    const res = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      throw new Error(`HTTP error ${res.status}: ${res.statusText}`);
    }
    return await res.json();
  }

  const api = {
    apiGet,
    apiPost,

    async getState() {
      return await apiGet("/api/state");
    },

    async fetchState() {
      return await apiGet("/api/state");
    },

    async selectImage(index) {
      return await apiPost("/api/layerify/select-image", { index });
    },

    async selectFolder(folderPath) {
      return await apiPost("/api/layerify/select-folder", { folder_path: folderPath });
    },

    async browseFolders(pathStr = "") {
      return await apiGet(`/api/layerify/browse-folders?path=${encodeURIComponent(pathStr)}`);
    },

    async uploadImages(files) {
      const data = new FormData();
      for (const f of files) {
        data.append("files", f);
      }
      const res = await fetch("/api/layerify/upload-images", {
        method: "POST",
        body: data
      });
      if (!res.ok) throw new Error(`Upload failed with status ${res.status}`);
      return await res.json();
    },

    async updateAnnotations(annotations, pushUndo = true, message = "") {
      return await apiPost("/api/layerify/annotations/update", {
        annotations,
        push_undo: pushUndo,
        message
      });
    },

    async performAnnotationAction(action, extra = {}) {
      return await apiPost("/api/layerify/annotations/action", {
        action,
        ...extra
      });
    },

    async runModelPrediction(modelName, textPrompt = "") {
      return await apiPost("/api/layerify/model", {
        action: "predict",
        model_name: modelName,
        text_prompt: textPrompt,
        prompt: textPrompt
      });
    },

    async selectModel(modelName) {
      return await apiPost("/api/layerify/model", {
        action: "select",
        model_name: modelName
      });
    },

    async layerifyAll(annotationIds = null) {
      return await apiPost("/api/layerify/layerify", {
        annotation_ids: annotationIds
      });
    },

    async saveAnnotations(filename, fmt = "default", classNames = null) {
      return await apiPost("/api/layerify/annotations/save", {
        filename,
        format: fmt,
        class_names: classNames
      });
    },

    async loadAnnotations(content, fmt = "auto", classNames = null) {
      return await apiPost("/api/layerify/annotations/load", {
        content,
        format: fmt,
        class_names: classNames
      });
    },

    async manageLabels(payload) {
      return await apiPost("/api/layerify/labels", payload);
    },

    async manageCanvas(payload) {
      return await apiPost("/api/baker/canvas", payload);
    },

    async addBlankLayer(name = "Blank Layer", color = "#ffffff") {
      return await apiPost("/api/baker/layers/add-blank", { name, color });
    },

    async updateBakerLayers(layers, pushUndo = true, message = "") {
      return await apiPost("/api/baker/layers/update", {
        layers,
        push_undo: pushUndo,
        message
      });
    },

    async reorderBakerLayers(orderOrPayload) {
      let payload;
      if (typeof orderOrPayload === "string") {
        payload = { direction: orderOrPayload };
      } else if (Array.isArray(orderOrPayload)) {
        payload = { order: orderOrPayload };
      } else {
        payload = orderOrPayload;
      }
      return await apiPost("/api/baker/layers/reorder", payload);
    },

    async performBakerLayerAction(action, extra = {}) {
      return await apiPost("/api/baker/layers/action", {
        action,
        ...extra
      });
    },

    async managePlugins(payload) {
      return await apiPost("/api/baker/plugins", payload);
    },

    async manageStates(payload) {
      return await apiPost("/api/baker/states", payload);
    },

    async exportBaker(mode, annotationFormat = "default") {
      return await apiPost("/api/baker/export", {
        mode,
        annotation_format: annotationFormat
      });
    },

    async updateSettings(settings) {
      return await apiPost("/api/settings", settings);
    }
  };

  window.ImageBaker = window.ImageBaker || {};
  window.ImageBaker.api = api;
})(window);

