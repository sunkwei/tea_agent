const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    readCalendar: () => ipcRenderer.invoke('read-calendar'),
    openExternal: (url) => ipcRenderer.invoke('open-external', url),
    fetchArticleContent: (url) => ipcRenderer.invoke('fetch-article-content', url),
    fetchOgImage: (url) => ipcRenderer.invoke('fetch-og-image', url),
    getCachedOgImages: () => ipcRenderer.invoke('get-cached-og-images'),
    // 新闻
    fetchNews: (forceRefresh) => ipcRenderer.invoke('fetch-news', forceRefresh),
    onNewsFetched: (callback) => {
        ipcRenderer.on('news-fetched', (_, data) => callback(data));
    },
    onCalendarUpdated: (callback) => {
        ipcRenderer.on('calendar-updated', (_, data) => callback(data));
    }
});
