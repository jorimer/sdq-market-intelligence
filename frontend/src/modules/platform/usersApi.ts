import client from "@/shared/api/client";

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  role: string;
  tier: string;
  is_active: boolean;
  created_at?: string | null;
}

export interface CreateUserInput {
  email: string;
  password: string;
  full_name: string;
  role: string;
  tier: string;
}

export interface UpdateUserInput {
  full_name?: string;
  role?: string;
  tier?: string;
  is_active?: boolean;
}

export async function listUsers(): Promise<AdminUser[]> {
  const { data } = await client.get<AdminUser[]>("/admin/users");
  return data;
}

export async function createUser(input: CreateUserInput): Promise<AdminUser> {
  const { data } = await client.post<AdminUser>("/admin/users", input);
  return data;
}

export async function updateUser(id: string, input: UpdateUserInput): Promise<AdminUser> {
  const { data } = await client.patch<AdminUser>(`/admin/users/${id}`, input);
  return data;
}

export async function resetUserPassword(id: string, newPassword: string): Promise<void> {
  await client.post(`/admin/users/${id}/reset-password`, { new_password: newPassword });
}

export async function deleteUser(id: string): Promise<void> {
  await client.delete(`/admin/users/${id}`);
}
