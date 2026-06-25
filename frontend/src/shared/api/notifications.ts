import client from "@/shared/api/client";

/** Buzón de notificaciones in-app (transversal). El backend ya aísla por usuario. */
export interface AppNotification {
  id: string;
  type: string; // info | warning | error | success
  title: string;
  body: string | null;
  read: boolean;
  created_at: string | null;
}

export interface NotificationList {
  notifications: AppNotification[];
  unread: number;
}

export async function getNotifications(unreadOnly = false): Promise<NotificationList> {
  const { data } = await client.get("/notifications", {
    params: { unread_only: unreadOnly },
  });
  return data;
}

export async function getUnreadCount(): Promise<number> {
  const { data } = await client.get("/notifications/unread-count");
  return data.unread as number;
}

export async function markNotificationRead(id: string): Promise<void> {
  await client.post(`/notifications/${encodeURIComponent(id)}/read`);
}

export async function markAllNotificationsRead(): Promise<number> {
  const { data } = await client.post("/notifications/read-all");
  return data.updated as number;
}
