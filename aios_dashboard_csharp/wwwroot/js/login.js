// ponytail: minimal fetch bridge — upgrade to typed endpoint when needed
window.aiosLogin = async function (username, password) {
    try {
        var r = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ Username: username, Password: password }),
            credentials: "same-origin"
        });
        var j = await r.json().catch(function () { return {}; });
        return j && j.success === true;
    } catch (e) {
        return false;
    }
};
