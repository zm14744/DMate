package app.dmate.client;

import java.util.HashSet;
import java.util.Set;

public final class GuestSessionTest {
    private static void check(boolean expected, String message) {
        if (!expected) throw new AssertionError(message);
    }

    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("script")) {
            System.out.print(GuestSession.script("test-launch-token-1234567890"));
            return;
        }
        String process = GuestSession.processToken();
        String initial = GuestSession.start(null, null);
        check(initial.equals(GuestSession.start(process, initial)), "Activity recreation must retain the live guest session");
        check(!initial.equals(GuestSession.start("another-process", initial)), "Process death must not restore the old guest session");
        check(!initial.equals(GuestSession.start(null, initial)), "Fresh launch must not restore a saved session without its process");
        check(!initial.equals(GuestSession.start(process, "unknown-session-token")), "Unknown restored windows must start fresh");
        GuestSession.end(initial);
        check(!initial.equals(GuestSession.start(process, initial)), "A closed window must not reopen its old guest session");
        Set<String> starts = new HashSet<>();
        for (int index = 0; index < 40; index++) starts.add(GuestSession.start(null, null));
        check(starts.size() == 40, "Fresh app windows must not share a session");
        for (String invalid : new String[] {"", "too-short", "arbitrary-script');alert(1)//"}) {
            boolean rejected = false;
            try { GuestSession.script(invalid); } catch (IllegalArgumentException expected) { rejected = true; }
            check(rejected, "Native script markers must have safe characters and length");
        }
        System.out.println("PASS Android guest launch, recreation, process restore and explicit-close lifetimes");
    }
}
