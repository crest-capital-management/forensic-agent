import { redirect } from "next/navigation";

// The old address: the profile page now holds the password form.
export default function Account() {
  redirect("/profile#password");
}
