self.addEventListener("push", (event) => {
  if (!event.data) return;
  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: "AskBuddy", body: event.data.text(), destination: "/owner/notifications" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "AskBuddy", {
      body: data.body || "새 알림이 있어요.",
      icon: data.icon || "/images/buddy-hero.png",
      badge: "/images/buddy-hero.png",
      tag: data.notification_id ? `askbuddy-${data.notification_id}` : undefined,
      data: { destination: data.destination || "/owner/notifications" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destination = event.notification.data?.destination || "/owner/notifications";
  const target = new URL(destination, self.location.origin).href;
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const existing = windows.find((client) => client.url.startsWith(self.location.origin));
      if (existing) {
        return existing.navigate(target).then((client) => client?.focus());
      }
      return clients.openWindow(target);
    })
  );
});
