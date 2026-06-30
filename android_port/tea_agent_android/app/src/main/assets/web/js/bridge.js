/**
 * @2026-05-16 gen by tea_agent, TeaBridge — JS ↔ Kotlin 事件桥接
 */
var TeaBridge = (function() {
    'use strict';
    var listeners = {};

    // Kotlin → JS 事件入口
    function emit(event, data) {
        var parsed;
        try { parsed = JSON.parse(data); } catch(e) { parsed = {text:data}; }
        (listeners[event] || []).forEach(function(fn) {
            try { fn(parsed); } catch(e) { console.error(e); }
        });
        (listeners['*'] || []).forEach(function(fn) {
            try { fn(event, parsed); } catch(e) {}
        });
    }

    function on(event, fn) {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(fn);
        return function() { off(event, fn); };
    }
    function off(event, fn) {
        if (!listeners[event]) return;
        if (fn) listeners[event] = listeners[event].filter(function(f){return f!==fn;});
        else delete listeners[event];
    }

    // 封装原生调用
    function call(method) {
        var args = Array.prototype.slice.call(arguments, 1);
        if (typeof TeaNative !== 'undefined' && TeaNative[method]) {
            var json = args.length > 0 ? JSON.stringify(args[0]) : '{}';
            return TeaNative[method](json);
        }
        return null;
    }

    return {
        emit: emit, on: on, off: off,
        // Chat
        chatSend: function(msg, topicId) { call('chatSend', {message:msg, topic_id:topicId}); },
        chatStop: function() { call('chatStop'); },
        // Config
        configGet: function() { var r = TeaNative ? TeaNative.configGet() : '{}'; try{return JSON.parse(r);}catch(e){return{};} },
        configSet: function(cfg) { call('configSet', cfg); },
        // Topics
        topicList: function() { var r = TeaNative?TeaNative.topicList():'[]'; try{return JSON.parse(r);}catch(e){return[];} },
        topicNew: function(title) { return TeaNative ? TeaNative.topicNew(title) : ''; },
        topicDelete: function(id) { call('topicDelete', {topic_id:id}); },
        topicRename: function(id, title) { call('topicRename', {topic_id:id, title:title}); },
        topicHardDelete: function(id) { call('topicHardDelete', {topic_id:id}); },
        topicMessages: function(id) { var r = TeaNative?TeaNative.topicMessages(id):'[]'; try{return JSON.parse(r);}catch(e){return[];} },
        topicTokenStats: function(id) { var r = TeaNative?TeaNative.topicTokenStats(id):'{}'; try{return JSON.parse(r);}catch(e){return{};} },
        // Tools
        toolSave: function(name, meta, code) { return TeaNative ? TeaNative.toolSave(name, JSON.stringify(meta||{}), code) : ''; },
        toolReload: function() { return TeaNative ? TeaNative.toolReload() : ''; },
        toolList: function() { var r = TeaNative?TeaNative.toolList():'[]'; try{return JSON.parse(r);}catch(e){return[];} },
        // System
        notify: function(t,m) { if(TeaNative) TeaNative.systemNotify(t,m); },
        copy: function(t) { if(TeaNative) TeaNative.copyToClipboard(t); }
    };
})();
window.TeaBridge = TeaBridge;
