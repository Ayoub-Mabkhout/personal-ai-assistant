// Linked device receiver with an explicit, local self-chat outbox.
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/proto/waE2E"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	_ "modernc.org/sqlite"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

var statusLock sync.Mutex

type selfMessage struct {
	Text      string `json:"text"`
	State     string `json:"state"`
	MessageID string `json:"message_id,omitempty"`
	SentAt    string `json:"sent_at,omitempty"`
}

// Only the linked account's own chat is addressable. A claimed send is never
// automatically retried after a crash or ambiguous acknowledgement.
func selfOutbox(ctx context.Context, dir string, client *whatsmeow.Client) {
	folder := filepath.Join(dir, "self-outbox")
	if os.MkdirAll(folder, 0700) != nil {
		return
	}
	write := func(path string, value selfMessage) error {
		data, err := json.Marshal(value)
		if err != nil {
			return err
		}
		if err = os.WriteFile(path+".tmp", data, 0600); err != nil {
			return err
		}
		return os.Rename(path+".tmp", path)
	}
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if !client.IsConnected() || !client.IsLoggedIn() || client.Store.ID == nil {
				continue
			}
			entries, err := os.ReadDir(folder)
			if err != nil {
				continue
			}
			for _, entry := range entries {
				if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
					continue
				}
				path := filepath.Join(folder, entry.Name())
				info, err := entry.Info()
				if err != nil || info.Size() > 16384 {
					continue
				}
				data, err := os.ReadFile(path)
				var message selfMessage
				if err != nil || json.Unmarshal(data, &message) != nil || message.State != "pending" || len(strings.TrimSpace(message.Text)) == 0 || len(message.Text) > 4096 {
					continue
				}
				message.State = "sending"
				message.MessageID = string(client.GenerateMessageID())
				if write(path, message) != nil {
					continue
				}
				response, err := client.SendMessage(ctx, client.Store.ID.ToNonAD(), &waE2E.Message{Conversation: proto.String(message.Text)}, whatsmeow.SendRequestExtra{ID: types.MessageID(message.MessageID), Timeout: 30 * time.Second})
				if err != nil {
					message.State = "uncertain"
				} else {
					message.State = "sent"
					message.SentAt = response.Timestamp.UTC().Format(time.RFC3339)
				}
				if write(path, message) != nil {
					fmt.Println("self-chat receipt persistence failed")
				}
			}
		}
	}
}

func status(dir, state string, expiry ...time.Time) {
	statusLock.Lock()
	defer statusLock.Unlock()
	value := map[string]any{"state": state, "updated_at": time.Now().UTC().Format(time.RFC3339)}
	if len(expiry) > 0 {
		value["qr_expires_at"] = expiry[0].UTC().Format(time.RFC3339)
	}
	data, _ := json.Marshal(value)
	path := filepath.Join(dir, "status.json")
	if err := os.WriteFile(path+".tmp", data, 0600); err != nil {
		return
	}
	if err := os.Rename(path+".tmp", path); err != nil {
		fmt.Println("status persistence failed")
	}
}

func run() error {
	directory := flag.String("runtime", "", "Protected directory for linked-device credentials and inbox")
	flag.Parse()
	if *directory == "" {
		return fmt.Errorf("--runtime is required")
	}
	dir, err := filepath.Abs(*directory)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	db, err := sql.Open("sqlite", "file:"+filepath.ToSlash(filepath.Join(dir, "session.sqlite3"))+"?_pragma=foreign_keys(1)&_pragma=busy_timeout(10000)")
	if err != nil {
		return err
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	container := sqlstore.NewWithDB(db, "sqlite3", nil)
	if err = container.Upgrade(ctx); err != nil {
		return err
	}
	device, err := container.GetFirstDevice(ctx)
	if err != nil {
		return err
	}
	inbox, err := sql.Open("sqlite", "file:"+filepath.ToSlash(filepath.Join(dir, "inbox.sqlite3"))+"?_pragma=busy_timeout(10000)")
	if err != nil {
		return err
	}
	defer inbox.Close()
	inbox.SetMaxOpenConns(1)
	if _, err = inbox.Exec(`PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS messages(chat TEXT,message_id TEXT,sender TEXT,sent_at INTEGER,from_me INTEGER,text TEXT,payload TEXT,history INTEGER,PRIMARY KEY(chat,message_id)); CREATE TABLE IF NOT EXISTS archive_errors(at TEXT,kind TEXT);`); err != nil {
		return err
	}
	client := whatsmeow.NewClient(device, nil)
	defer client.Disconnect()
	client.EnableAutoReconnect = true
	client.InitialAutoReconnect = true
	archive := func(msg *events.Message, history bool) {
		// View-once media and ephemeral messages are deliberately not archived.
		if msg.IsViewOnce || msg.IsEphemeral {
			return
		}
		payload, e := protojson.Marshal(msg.Message)
		if e != nil {
			return
		}
		text := msg.Message.GetConversation()
		if text == "" {
			text = msg.Message.GetExtendedTextMessage().GetText()
		}
		if text == "" {
			text = msg.Message.GetImageMessage().GetCaption()
		}
		_, e = inbox.Exec(`INSERT INTO messages VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chat,message_id) DO UPDATE SET text=excluded.text,payload=excluded.payload`, msg.Info.Chat.String(), string(msg.Info.ID), msg.Info.Sender.String(), msg.Info.Timestamp.Unix(), msg.Info.IsFromMe, text, string(payload), history)
		if e != nil {
			fmt.Println("inbox write failed")
			inbox.Exec("INSERT INTO archive_errors VALUES(?,?)", time.Now().UTC().Format(time.RFC3339), "message_write")
		}
	}
	client.AddEventHandler(func(raw any) {
		switch event := raw.(type) {
		case *events.PairError:
			status(dir, "pairing_failed")
			fmt.Printf("pairing handshake failed: %v\n", event.Error)
		case *events.PairSuccess:
			status(dir, "paired")
			os.Remove(filepath.Join(dir, "pairing.png"))
		case *events.Connected:
			status(dir, "connected")
			os.Remove(filepath.Join(dir, "pairing.png"))
		case *events.Disconnected:
			status(dir, "disconnected")
		case *events.LoggedOut:
			status(dir, "logged_out")
			os.Remove(filepath.Join(dir, "pairing.png"))
			cancel()
		case *events.Message:
			archive(event, false)
		case *events.HistorySync:
			for _, conversation := range event.Data.GetConversations() {
				jid, e := types.ParseJID(conversation.GetID())
				if e != nil {
					continue
				}
				for _, message := range conversation.GetMessages() {
					msg, e := client.ParseWebMessage(jid, message.GetMessage())
					if e == nil {
						archive(msg, true)
					}
				}
			}
		}
	})
	if device.ID == nil {
		qr, err := client.GetQRChannel(ctx)
		if err != nil {
			return err
		}
		if err = client.Connect(); err != nil {
			return err
		}
		paired := false
		for event := range qr {
			if event.Event == "code" {
				png, e := qrcode.Encode(event.Code, qrcode.Medium, 512)
				if e != nil {
					return e
				}
				path := filepath.Join(dir, "pairing.png")
				if e = os.WriteFile(path+".tmp", png, 0600); e != nil {
					return e
				}
				if e = os.Rename(path+".tmp", path); e != nil {
					return e
				}
				status(dir, "pairing", time.Now().Add(event.Timeout))
			}
			if event.Event == "success" {
				paired = true
			}
			if event.Event == "error" || len(event.Event) > 4 && event.Event[:4] == "err-" {
				status(dir, "pairing_failed")
				os.Remove(filepath.Join(dir, "pairing.png"))
				return fmt.Errorf("pairing event %s: %v", event.Event, event.Error)
			}
			if event.Event == "timeout" {
				status(dir, "pairing_expired")
				os.Remove(filepath.Join(dir, "pairing.png"))
				client.Disconnect()
				return fmt.Errorf("pairing window expired")
			}
		}
		if !paired {
			return fmt.Errorf("pairing channel closed without success")
		}
	} else {
		status(dir, "connecting")
		if err = client.Connect(); err != nil {
			return err
		}
	}
	go selfOutbox(ctx, dir, client)
	<-ctx.Done()
	client.Disconnect()
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Println("WhatsApp receiver stopped:", err)
		os.Exit(1)
	}
}
